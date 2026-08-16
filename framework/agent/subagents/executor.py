from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from framework.agent.runtime.redaction import redact_sensitive_values
from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TelemetrySpanLink,
    W3CTracePropagator,
    default_event_telemetry,
    trace_context_scope,
)
from framework.events.propagation import normalize_trace_carrier

if TYPE_CHECKING:
    from framework.agent.models import AgentLoopResult, AgentSpec
    from framework.llm.budget import GlobalBudgetTracker
    from framework.llm.models import LLMClient
    from framework.tool import ToolRegistry


class SubAgentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SubAgentTask:
    parent_agent_id: str
    child_agent_id: str
    task: str
    inputs: dict[str, Any] = field(default_factory=dict)
    handoff_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_carrier: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trace_carrier",
            normalize_trace_carrier(self.trace_carrier),
        )

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        inputs = dict(self.inputs)
        metadata = dict(self.metadata)
        return {
            "parent_agent_id": self.parent_agent_id,
            "child_agent_id": self.child_agent_id,
            "task": self.task,
            "inputs": redact_sensitive_values(inputs) if redact else inputs,
            "handoff_reason": self.handoff_reason,
            "metadata": redact_sensitive_values(metadata) if redact else metadata,
            "trace_carrier": dict(self.trace_carrier),
        }


@dataclass(frozen=True)
class SubAgentResult:
    child_agent_id: str
    success: bool
    status: SubAgentStatus | str = SubAgentStatus.SUCCEEDED
    output: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        output = dict(self.output)
        events = [dict(event) for event in self.events]
        metrics = dict(self.metrics)
        artifact_refs = [dict(ref) for ref in self.artifact_refs]
        metadata = dict(self.metadata)
        payload = {
            "child_agent_id": self.child_agent_id,
            "success": self.success,
            "status": _status_value(self.status),
            "output": output,
            "summary": self.summary,
            "error": self.error,
            "events": events,
            "metrics": metrics,
            "artifact_refs": artifact_refs,
            "metadata": metadata,
        }
        return redact_sensitive_values(payload) if redact else payload


class SubAgentExecutor(Protocol):
    def execute(self, task: SubAgentTask) -> SubAgentResult:
        """Execute a child agent against a read-only parent snapshot."""
        ...

    def run(self, task: SubAgentTask) -> SubAgentResult:
        """Run a child agent against a read-only parent snapshot."""
        ...


class LocalSubAgentExecutor:
    """Minimal in-process sub-agent executor backed by AgentRunner."""

    def __init__(
        self,
        *,
        agents: Mapping[str, "AgentSpec"],
        llm_client: "LLMClient",
        tool_registry: "ToolRegistry",
        conversation_store: Any | None = None,
        global_budget_tracker: "GlobalBudgetTracker | None" = None,
        allow_nested_subagents: bool = False,
        trace_propagator: W3CTracePropagator | None = None,
        telemetry: EventTelemetry | None = None,
    ) -> None:
        self._agents = dict(agents)
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._conversation_store = conversation_store
        self._global_budget_tracker = global_budget_tracker
        self._allow_nested_subagents = allow_nested_subagents
        self._trace_propagator = trace_propagator or W3CTracePropagator()
        self._telemetry = telemetry or default_event_telemetry(
            resource=TelemetryResource(service_name="newsroom-agent-runtime"),
            scope=TelemetryInstrumentationScope(
                name="framework.agent.subagents",
                version="1",
            ),
        )

    def run(self, task: SubAgentTask) -> SubAgentResult:
        agent = self._agents.get(task.child_agent_id)
        if agent is None:
            return SubAgentResult(
                child_agent_id=task.child_agent_id,
                success=False,
                status=SubAgentStatus.FAILED,
                error=f"subagent is not registered: {task.child_agent_id}",
                metadata={"parent_agent_id": task.parent_agent_id},
            )

        child_agent = agent if self._allow_nested_subagents else _disable_nested_subagents(agent)
        child_inputs = _child_inputs(task)
        conversation_id = _optional_metadata_str(task.metadata, "conversation_id")

        from framework.agent.loop.runner import AgentRunner

        extracted = self._trace_propagator.extract_span(task.trace_carrier)
        child_trace = extracted.child().context
        trace_link = TelemetrySpanLink.from_context(
            extracted.remote_context,
            relationship="subagent_handoff",
        )
        with trace_context_scope(child_trace), self._telemetry.start_span(
            "newsroom.subagent.execute",
            attributes={
                "newsroom.component": "subagent",
                "newsroom.operation": "execute",
                "newsroom.transport": "worker",
            },
            links=(trace_link,),
        ):
            child_budget_tracker = (
                self._global_budget_tracker.child_tracker(
                    (
                        f"subagent:{task.parent_agent_id}:{task.child_agent_id}:"
                        f"{_optional_metadata_str(task.metadata, 'run_id') or 'run'}"
                    )
                )
                if self._global_budget_tracker is not None
                else None
            )
            result = AgentRunner(
                llm_client=self._llm_client,
                tool_registry=self._tool_registry,
                conversation_store=self._conversation_store,
                global_budget_tracker=child_budget_tracker,
                subagent_executor=self if self._allow_nested_subagents else None,
            ).run(
                child_agent,
                child_inputs,
                conversation_id=conversation_id,
                run_id=_optional_metadata_str(task.metadata, "run_id"),
                node_instance_id=_optional_metadata_str(
                    task.metadata,
                    "node_instance_id",
                ),
                graph_checkpoint_ref=_optional_metadata_str(
                    task.metadata,
                    "graph_checkpoint_ref",
                ),
                resume_from_cursor=bool(
                    task.metadata.get("resume_from_cursor", False)
                ),
            )
        return _result_to_subagent_result(task, result)

    def execute(self, task: SubAgentTask) -> SubAgentResult:
        return self.run(task)


def _status_value(status: SubAgentStatus | str) -> str:
    return status.value if isinstance(status, SubAgentStatus) else str(status)


def _disable_nested_subagents(agent: "AgentSpec") -> "AgentSpec":
    return replace(
        agent,
        loop_policy=replace(agent.loop_policy, allow_subagents=False),
        allowed_subagents=[],
    )


def _child_inputs(task: SubAgentTask) -> dict[str, Any]:
    child_inputs = {
        "subagent_task": task.task,
        "handoff_reason": task.handoff_reason,
        "parent_agent_id": task.parent_agent_id,
        **deepcopy(task.inputs),
    }
    for key in ("run_id", "graph_id"):
        value = task.metadata.get(key)
        if key not in child_inputs and value:
            child_inputs[key] = str(value)
    return child_inputs


def _optional_metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _result_to_subagent_result(
    task: SubAgentTask,
    result: "AgentLoopResult",
) -> SubAgentResult:
    status = SubAgentStatus.SUCCEEDED if result.success else result.status.value
    diagnostics = result.diagnostics.to_dict() if result.diagnostics else {}
    return SubAgentResult(
        child_agent_id=task.child_agent_id,
        success=result.success,
        status=status,
        output=dict(result.output),
        summary=str(diagnostics.get("summary") or result.error or ""),
        error=str(result.error) if result.error is not None else None,
        events=[dict(event) for event in result.events],
        metrics=result.metrics.to_dict(),
        artifact_refs=[artifact.to_dict() for artifact in result.llm_call_artifacts],
        metadata={
            "parent_agent_id": task.parent_agent_id,
            "stop_reason": diagnostics.get("stop_reason"),
            "iterations": result.iterations,
        },
    )
