from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.framework.llm import TokenUsage
from core.framework.tools.boundary import harden_restricted_agent_tool_policy
from core.framework.tools.models import ToolPolicy


class AgentLoopStatus(str, Enum):
    ACCEPTED = "accepted"
    RETRY_EXHAUSTED = "retry_exhausted"
    BLOCKED = "blocked"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    STALLED = "stalled"
    FAILED = "failed"


class JudgeDecision(str, Enum):
    ACCEPT = "accept"
    RETRY = "retry"
    ESCALATE = "escalate"
    BLOCK = "block"


class AgentLoopStopReason(str, Enum):
    FINAL_OUTPUT_ACCEPTED = "final_output_accepted"
    CONTROL_OUTPUT_ACCEPTED = "control_output_accepted"
    JUDGE_BLOCKED = "judge_blocked"
    SECRET_BLOCKED = "secret_blocked"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    TOOL_BUDGET_EXCEEDED = "tool_budget_exceeded"
    AGENT_POLICY_BLOCKED = "agent_policy_blocked"
    REPEATED_TOOL_CALL_STALLED = "repeated_tool_call_stalled"
    PARSER_RETRY_EXHAUSTED = "parser_retry_exhausted"
    JUDGE_RETRY_EXHAUSTED = "judge_retry_exhausted"
    EMPTY_OUTPUT_EXHAUSTED = "empty_output_exhausted"
    MAX_ITERATIONS_EXCEEDED = "max_iterations_exceeded"
    LLM_FAILED = "llm_failed"
    GLOBAL_BUDGET_EXCEEDED = "global_budget_exceeded"
    TOOL_FAILED = "tool_failed"
    UNKNOWN_FAILED = "unknown_failed"


class AgentLoopEventType(str, Enum):
    AGENT_STARTED = "agent_started"
    ITERATION_STARTED = "iteration_started"
    LLM_CALL = "llm_call"
    LLM_STREAM_EVENT = "llm_stream_event"
    LLM_CALL_FAILED = "llm_call_failed"
    ACTION_PARSED = "action_parsed"
    PARSER_ERROR = "parser_error"
    TOOL_CALL = "tool_call"
    TOOL_OBSERVATION = "tool_observation"
    TOOL_BUDGET_BLOCKED = "tool_budget_blocked"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    REPEATED_TOOL_CALL_DETECTED = "repeated_tool_call_detected"
    SUBAGENT_DELEGATION_REQUESTED = "subagent_delegation_requested"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
    JUDGE_ACCEPT = "judge_accept"
    JUDGE_RETRY = "judge_retry"
    JUDGE_BLOCK = "judge_block"
    FINAL_OUTPUT = "final_output"
    AGENT_WAITING_FOR_APPROVAL = "agent_waiting_for_approval"
    AGENT_BLOCKED = "agent_blocked"
    AGENT_STALLED = "agent_stalled"
    AGENT_RETRY_EXHAUSTED = "agent_retry_exhausted"
    AGENT_FAILED = "agent_failed"
    AGENT_COMPLETED = "agent_completed"


class AgentLoopDiagnosticSeverity(str, Enum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AgentLoopPolicy:
    max_iterations: int = 5
    max_judge_retries: int = 2
    max_parser_errors: int = 2
    max_repeated_tool_calls: int = 2
    max_consecutive_tool_failures: int = 3
    stop_on_first_valid_output: bool = True
    stall_detection_enabled: bool = True
    trace_enabled: bool = True
    max_trace_preview_chars: int = 500
    llm_streaming_enabled: bool = False
    conversation_compaction_enabled: bool = True
    conversation_compaction_max_messages: int = 50
    conversation_compaction_keep_last: int = 10
    allow_subagents: bool = False

    def __post_init__(self) -> None:
        _validate_non_negative("max_iterations", self.max_iterations, minimum=1)
        _validate_non_negative("max_judge_retries", self.max_judge_retries)
        _validate_non_negative("max_parser_errors", self.max_parser_errors)
        _validate_non_negative("max_repeated_tool_calls", self.max_repeated_tool_calls)
        _validate_non_negative(
            "max_consecutive_tool_failures",
            self.max_consecutive_tool_failures,
        )
        _validate_non_negative("max_trace_preview_chars", self.max_trace_preview_chars)
        _validate_non_negative(
            "conversation_compaction_max_messages",
            self.conversation_compaction_max_messages,
            minimum=1,
        )
        _validate_non_negative(
            "conversation_compaction_keep_last",
            self.conversation_compaction_keep_last,
        )


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    role: str
    goal: str
    instructions: str
    input_keys: list[str]
    output_key: str
    output_schema: dict[str, Any] | None = None
    allowed_tools: list[str] = field(default_factory=list)
    loop_policy: AgentLoopPolicy = field(default_factory=AgentLoopPolicy)
    tool_policy: ToolPolicy | None = None
    model_policy: dict[str, Any] = field(default_factory=dict)
    evidence_policy: dict[str, Any] = field(default_factory=dict)
    system_prompt_template: str = "{role}\n{instructions}"
    task_prompt_template: str = "Goal: {goal}\nInputs: {inputs}"
    allowed_sources: list[str] = field(default_factory=list)
    allowed_subagents: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise ValueError("agent_id is required")

    def resolved_tool_policy(self) -> ToolPolicy:
        if self.tool_policy:
            return _harden_agent_loop_tool_policy(
                self.agent_id,
                harden_restricted_agent_tool_policy(self.agent_id, self.tool_policy),
            )
        return _harden_agent_loop_tool_policy(
            self.agent_id,
            harden_restricted_agent_tool_policy(
                self.agent_id,
                ToolPolicy(
                    allowed_tools=list(self.allowed_tools),
                    require_explicit_allowlist=True,
                ),
            ),
        )

    @property
    def allow_subagents(self) -> bool:
        return bool(self.loop_policy.allow_subagents)

    def allows_subagent(self, child_agent_id: str) -> bool:
        return self.allow_subagents and child_agent_id in set(self.allowed_subagents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "instructions": self.instructions,
            "input_keys": list(self.input_keys),
            "output_key": self.output_key,
            "output_schema": _copy_mapping(self.output_schema),
            "allowed_tools": list(self.allowed_tools),
            "loop_policy": _agent_loop_policy_to_dict(self.loop_policy),
            "tool_policy": (
                _tool_policy_to_dict(self.tool_policy)
                if self.tool_policy is not None
                else None
            ),
            "model_policy": dict(self.model_policy),
            "evidence_policy": dict(self.evidence_policy),
            "system_prompt_template": self.system_prompt_template,
            "task_prompt_template": self.task_prompt_template,
            "allowed_sources": list(self.allowed_sources),
            "allowed_subagents": list(self.allowed_subagents),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentSpec:
        return cls(
            agent_id=str(payload.get("agent_id") or ""),
            name=str(payload.get("name") or ""),
            role=str(payload.get("role") or ""),
            goal=str(payload.get("goal") or ""),
            instructions=str(payload.get("instructions") or ""),
            input_keys=[str(item) for item in payload.get("input_keys", [])],
            output_key=str(payload.get("output_key") or ""),
            output_schema=_optional_mapping(payload.get("output_schema")),
            allowed_tools=[str(item) for item in payload.get("allowed_tools", [])],
            loop_policy=_agent_loop_policy_from_dict(payload.get("loop_policy")),
            tool_policy=_tool_policy_from_dict(payload.get("tool_policy")),
            model_policy=dict(payload.get("model_policy") or {}),
            evidence_policy=dict(payload.get("evidence_policy") or {}),
            system_prompt_template=str(
                payload.get("system_prompt_template") or "{role}\n{instructions}"
            ),
            task_prompt_template=str(
                payload.get("task_prompt_template") or "Goal: {goal}\nInputs: {inputs}"
            ),
            allowed_sources=[str(item) for item in payload.get("allowed_sources", [])],
            allowed_subagents=[str(item) for item in payload.get("allowed_subagents", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AgentAction:
    action_type: str
    output: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    subagent_id: str | None = None
    subagent_task: str | None = None
    handoff_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "output": self.output,
            "tool_name": self.tool_name,
            "tool_args": dict(self.tool_args),
            "subagent_id": self.subagent_id,
            "subagent_task": self.subagent_task,
            "handoff_reason": self.handoff_reason,
        }


@dataclass(frozen=True)
class JudgeVerdict:
    decision: JudgeDecision
    confidence: float = 0.0
    feedback: str | None = None
    missing_output_keys: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    quality_errors: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "feedback": self.feedback,
            "missing_output_keys": list(self.missing_output_keys),
            "schema_errors": list(self.schema_errors),
            "quality_errors": list(self.quality_errors),
            "policy_violations": list(self.policy_violations),
        }


@dataclass(frozen=True)
class AgentLoopIssue:
    code: str
    message: str
    severity: AgentLoopDiagnosticSeverity = AgentLoopDiagnosticSeverity.INFO
    iteration: int | None = None
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentLoopDiagnostics:
    agent_id: str
    status: AgentLoopStatus
    stop_reason: AgentLoopStopReason
    summary: str
    healthy: bool
    severity: AgentLoopDiagnosticSeverity
    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    parser_errors: int = 0
    judge_retries: int = 0
    tool_failures: int = 0
    tool_blocks: int = 0
    approval_requests: int = 0
    repeated_tool_calls: int = 0
    issues: list[AgentLoopIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    trace_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "stop_reason": self.stop_reason.value,
            "summary": self.summary,
            "healthy": self.healthy,
            "severity": self.severity.value,
            "iterations": self.iterations,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "parser_errors": self.parser_errors,
            "judge_retries": self.judge_retries,
            "tool_failures": self.tool_failures,
            "tool_blocks": self.tool_blocks,
            "approval_requests": self.approval_requests,
            "repeated_tool_calls": self.repeated_tool_calls,
            "issues": [issue.to_dict() for issue in self.issues],
            "suggestions": list(self.suggestions),
            "trace_summary": dict(self.trace_summary),
        }


@dataclass
class AgentLoopMetrics:
    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    parser_errors: int = 0
    judge_retries: int = 0
    judge_accepts: int = 0
    judge_blocks: int = 0
    tool_successes: int = 0
    tool_failures: int = 0
    tool_blocks: int = 0
    tool_timeouts: int = 0
    tool_approval_requests: int = 0
    repeated_tool_calls: int = 0
    stalled_iterations: int = 0
    llm_error_count: int = 0
    llm_stream_event_count: int = 0
    total_tool_elapsed_ms: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    global_budget_check: dict[str, Any] | None = None
    global_budget_usage: dict[str, Any] | None = None

    def add_usage(self, usage: TokenUsage) -> None:
        self.token_usage = TokenUsage(
            input_tokens=self.token_usage.input_tokens + usage.input_tokens,
            output_tokens=self.token_usage.output_tokens + usage.output_tokens,
        )

    def record_tool_status(self, status: Any, *, elapsed_ms: float = 0.0) -> None:
        status_value = getattr(status, "value", str(status))
        if status_value == "succeeded":
            self.tool_successes += 1
        elif status_value == "failed":
            self.tool_failures += 1
        elif status_value == "blocked":
            self.tool_blocks += 1
        elif status_value == "timeout":
            self.tool_timeouts += 1
        elif status_value == "approval_required":
            self.tool_approval_requests += 1
        self.total_tool_elapsed_ms += elapsed_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "parser_errors": self.parser_errors,
            "judge_retries": self.judge_retries,
            "judge_accepts": self.judge_accepts,
            "judge_blocks": self.judge_blocks,
            "tool_successes": self.tool_successes,
            "tool_failures": self.tool_failures,
            "tool_blocks": self.tool_blocks,
            "tool_timeouts": self.tool_timeouts,
            "tool_approval_requests": self.tool_approval_requests,
            "repeated_tool_calls": self.repeated_tool_calls,
            "stalled_iterations": self.stalled_iterations,
            "llm_error_count": self.llm_error_count,
            "llm_stream_event_count": self.llm_stream_event_count,
            "total_tool_elapsed_ms": self.total_tool_elapsed_ms,
            "token_usage": self.token_usage.to_dict(),
            "global_budget_check": self.global_budget_check,
            "global_budget_usage": self.global_budget_usage,
        }


@dataclass(frozen=True)
class LLMCallArtifact:
    artifact_id: str
    iteration: int
    request: dict[str, Any]
    response: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "iteration": self.iteration,
            "request": dict(self.request),
            "response": dict(self.response),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentLoopResult:
    success: bool
    status: AgentLoopStatus
    output: dict[str, Any] = field(default_factory=dict)
    verdict: JudgeVerdict | None = None
    iterations: int = 0
    metrics: AgentLoopMetrics = field(default_factory=AgentLoopMetrics)
    events: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    diagnostics: AgentLoopDiagnostics | None = None
    llm_call_artifacts: list[LLMCallArtifact] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "output": self.output,
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "iterations": self.iterations,
            "metrics": self.metrics.to_dict(),
            "events": [dict(event) for event in self.events],
            "trace": dict(self.trace),
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "llm_call_artifacts": [
                artifact.to_dict() for artifact in self.llm_call_artifacts
            ],
            "error": self.error,
        }


def _validate_non_negative(name: str, value: int, *, minimum: int = 0) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        if minimum == 0:
            raise ValueError(f"{name} must be non-negative")
        raise ValueError(f"{name} must be at least {minimum}")


def _agent_loop_policy_to_dict(policy: AgentLoopPolicy) -> dict[str, Any]:
    return {
        "max_iterations": policy.max_iterations,
        "max_judge_retries": policy.max_judge_retries,
        "max_parser_errors": policy.max_parser_errors,
        "max_repeated_tool_calls": policy.max_repeated_tool_calls,
        "max_consecutive_tool_failures": policy.max_consecutive_tool_failures,
        "stop_on_first_valid_output": policy.stop_on_first_valid_output,
        "stall_detection_enabled": policy.stall_detection_enabled,
        "trace_enabled": policy.trace_enabled,
        "max_trace_preview_chars": policy.max_trace_preview_chars,
        "llm_streaming_enabled": policy.llm_streaming_enabled,
        "conversation_compaction_enabled": policy.conversation_compaction_enabled,
        "conversation_compaction_max_messages": policy.conversation_compaction_max_messages,
        "conversation_compaction_keep_last": policy.conversation_compaction_keep_last,
        "allow_subagents": policy.allow_subagents,
    }


def _agent_loop_policy_from_dict(value: Any) -> AgentLoopPolicy:
    if not isinstance(value, dict):
        return AgentLoopPolicy()
    supported = _agent_loop_policy_to_dict(AgentLoopPolicy()).keys()
    return AgentLoopPolicy(**{key: value[key] for key in supported if key in value})


def _tool_policy_to_dict(policy: ToolPolicy) -> dict[str, Any]:
    return {
        "allowed_tools": list(policy.allowed_tools),
        "blocked_tools": list(policy.blocked_tools),
        "allow_mcp_tools": policy.allow_mcp_tools,
        "max_tool_calls_per_iteration": policy.max_tool_calls_per_iteration,
        "max_tool_calls_per_agent": policy.max_tool_calls_per_agent,
        "require_explicit_allowlist": policy.require_explicit_allowlist,
        "allow_dangerous_tools": policy.allow_dangerous_tools,
        "require_approval_for_side_effects": policy.require_approval_for_side_effects,
        "max_result_chars_inline": policy.max_result_chars_inline,
        "spill_large_results_to_artifact": policy.spill_large_results_to_artifact,
        "timeout_seconds_default": policy.timeout_seconds_default,
        "max_attempts_default": policy.max_attempts_default,
    }


def _tool_policy_from_dict(value: Any) -> ToolPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("tool_policy must be an object")
    supported = _tool_policy_to_dict(ToolPolicy()).keys()
    return ToolPolicy(**{key: value[key] for key in supported if key in value})


def _harden_agent_loop_tool_policy(agent_id: str, policy: ToolPolicy) -> ToolPolicy:
    normalized_agent_id = "".join(ch for ch in agent_id.casefold() if ch.isalnum())
    blocked_allowed_tools = set()
    if normalized_agent_id in {"editor", "editoragent"}:
        blocked_allowed_tools.update(
            tool_name
            for tool_name in policy.allowed_tools
            if _is_editor_mutation_tool(tool_name)
        )
    if not blocked_allowed_tools:
        return policy
    return ToolPolicy(
        allowed_tools=[
            tool_name
            for tool_name in policy.allowed_tools
            if tool_name not in blocked_allowed_tools
        ],
        blocked_tools=sorted({*policy.blocked_tools, *blocked_allowed_tools}),
        allow_mcp_tools=policy.allow_mcp_tools,
        max_tool_calls_per_iteration=policy.max_tool_calls_per_iteration,
        max_tool_calls_per_agent=policy.max_tool_calls_per_agent,
        require_explicit_allowlist=True,
        allow_dangerous_tools=policy.allow_dangerous_tools,
        require_approval_for_side_effects=policy.require_approval_for_side_effects,
        max_result_chars_inline=policy.max_result_chars_inline,
        spill_large_results_to_artifact=policy.spill_large_results_to_artifact,
        timeout_seconds_default=policy.timeout_seconds_default,
        max_attempts_default=policy.max_attempts_default,
    )


def _is_editor_mutation_tool(tool_name: str) -> bool:
    normalized = tool_name.strip()
    return (
        normalized.startswith("source.")
        or normalized in {"report.publish", "postgres.save_report"}
        or normalized.endswith(".publish")
        or normalized.endswith(".save_report")
    )


def _copy_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("output_schema must be an object")
    return dict(value)
