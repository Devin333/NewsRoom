from __future__ import annotations

import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._utils import (
    failed_outcome as _failed_outcome,
    validated_outputs as _validated_outputs,
    with_contract_metrics as _with_contract_metrics,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
)


class AgentLoopStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.AGENT_LOOP,
        runner_id="builtin.agent_loop",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["llm_client", "agent_registry"],
        description="Runs an AgentLoop step through the configured agent runner.",
    )

    def __init__(
        self,
        agent_runner: Any,
        agent_registry: dict[str, Any],
        global_budget_tracker: Any | None = None,
    ) -> None:
        self._agent_runner = agent_runner
        self._agent_registry = dict(agent_registry)
        self._global_budget_tracker = global_budget_tracker
        self._run_id: str | None = None

    def can_resolve(self, step: StepSpec) -> bool:
        if step.step_type != StepType.AGENT_LOOP:
            return False
        if self._agent_runner is None or not self._agent_registry:
            return True
        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        return agent_id in self._agent_registry

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.metadata.get("agent_id") or step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="agent_loop_missing_agent",
                message="AgentLoop step requires metadata.agent_id or implementation.",
                field="metadata.agent_id",
            )
        ]

    def configure_global_budget_tracker(
        self, global_budget_tracker: Any | None
    ) -> None:
        self._global_budget_tracker = global_budget_tracker

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        if step.step_type != StepType.AGENT_LOOP:
            return _failed_outcome(
                step,
                StepExecutionError(
                    f"unsupported step type for AgentLoopStepRunner: {step.step_type}"
                ),
                started=started,
                runner_name="AgentLoopStepRunner",
            )

        agent_id = str(step.metadata.get("agent_id") or step.implementation)
        try:
            agent = self._agent_registry[agent_id]
        except KeyError:
            return _failed_outcome(
                step,
                StepExecutionError(f"agent is not registered: {agent_id}"),
                started=started,
                runner_name="AgentLoopStepRunner",
            )

        input_keys = _agent_loop_input_keys(step)
        inputs = {key: buffer.read(key) for key in input_keys if buffer.exists(key)}
        conversation_id = step.metadata.get("conversation_id")
        if "conversation_id_key" in step.metadata:
            conversation_id = buffer.read(str(step.metadata["conversation_id_key"]))

        run_kwargs: dict[str, Any] = {
            "conversation_id": str(conversation_id) if conversation_id else None,
            "run_id": self._run_id,
            "step_id": step.step_id,
        }
        if bool(step.metadata.get("resume_from_conversation_cursor")) or bool(
            step.metadata.get("resume_from_cursor")
        ):
            run_kwargs["resume_from_cursor"] = True
        if "workflow_checkpoint_id" in step.metadata:
            run_kwargs["workflow_checkpoint_id"] = str(
                step.metadata["workflow_checkpoint_id"]
            )
        if self._global_budget_tracker is not None:
            run_kwargs["global_budget_tracker"] = self._global_budget_tracker
        result = self._agent_runner.run(agent, inputs, **run_kwargs)
        result_payload = result.to_dict()
        outputs: dict[str, Any] = {}
        if result.success:
            outputs.update(result.output)
        result_key = str(step.metadata.get("result_key") or "agent_loop_result")
        events_key = str(step.metadata.get("events_key") or "agent_loop_events")
        metrics_key = str(step.metadata.get("metrics_key") or "agent_loop_metrics")
        diagnostics_key = str(
            step.metadata.get("diagnostics_key") or "agent_loop_diagnostics"
        )
        trace_key = str(step.metadata.get("trace_key") or "agent_loop_trace")
        trajectory_key = str(
            step.metadata.get("trajectory_key") or "agent_loop_trajectory"
        )
        termination_key = str(
            step.metadata.get("termination_key") or "agent_loop_termination_reason"
        )
        max_steps_key = str(
            step.metadata.get("max_steps_key") or "agent_loop_max_steps_reached"
        )
        llm_artifacts_key = str(
            step.metadata.get("llm_artifacts_key") or "llm_call_artifacts"
        )
        outputs[result_key] = result_payload
        outputs[events_key] = result.events
        outputs[metrics_key] = result.metrics.to_dict()
        outputs[diagnostics_key] = (
            result.diagnostics.to_dict() if result.diagnostics is not None else None
        )
        outputs[trace_key] = result.trace
        outputs[trajectory_key] = [dict(item) for item in result_payload.get("trajectory") or []]
        outputs[termination_key] = result.termination_reason
        outputs[max_steps_key] = result.max_steps_reached
        outputs[llm_artifacts_key] = [
            artifact.to_dict() for artifact in result.llm_call_artifacts
        ]
        declared_outputs = _validated_outputs(
            step,
            outputs,
            runner_name="agent_loop step",
            allow_extra=True,
            allow_missing_required=not result.success,
        )

        for key, value in outputs.items():
            if key in buffer.list_allowed_writes():
                buffer.write(
                    key, value, lineage={"step_id": step.step_id, "agent_id": agent_id}
                )

        status_value = str(result.status.value)
        if result.success:
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=declared_outputs,
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "waiting_for_approval":
            return StepOutcome(
                status=StepStatus.PAUSED,
                outputs=declared_outputs,
                error_type="AgentLoopWaitingForApproval",
                error_message=result.error
                or f"agent loop waiting for approval: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "stalled":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=declared_outputs,
                error_type="AgentLoopStalled",
                error_message=result.error or f"agent loop stalled: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        if status_value == "blocked":
            return StepOutcome(
                status=StepStatus.BLOCKED,
                outputs=declared_outputs,
                error_type="AgentLoopBlocked",
                error_message=result.error or f"agent loop blocked: {agent_id}",
                error_details=_agent_loop_error_details(result_payload),
                metrics=_with_contract_metrics(
                    _agent_loop_metrics_payload(result),
                    step,
                    started=started,
                    outputs=declared_outputs,
                    artifact_count=len(result.llm_call_artifacts),
                ),
                trace_events=_agent_loop_trace_events(result),
            )
        return StepOutcome(
            status=StepStatus.FAILED,
            outputs=declared_outputs,
            error_type="AgentLoopFailed",
            error_message=result.error or f"agent loop failed: {agent_id}",
            error_details=_agent_loop_error_details(result_payload),
            metrics=_with_contract_metrics(
                _agent_loop_metrics_payload(result),
                step,
                started=started,
                outputs=declared_outputs,
                artifact_count=len(result.llm_call_artifacts),
            ),
            trace_events=_agent_loop_trace_events(result),
        )


def _agent_loop_error_details(result_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = result_payload.get("diagnostics")
    if isinstance(diagnostics, dict):
        details = {
            "agent_loop_status": result_payload.get("status"),
            "stop_reason": diagnostics.get("stop_reason"),
            "severity": diagnostics.get("severity"),
            "healthy": diagnostics.get("healthy"),
            "summary": diagnostics.get("summary"),
            "issues": diagnostics.get("issues") or [],
            "suggestions": diagnostics.get("suggestions") or [],
        }
        if diagnostics.get("stop_reason") == "global_budget_exceeded":
            details["budget_exceeded"] = True
            metrics = result_payload.get("metrics")
            if isinstance(metrics, dict):
                details["global_budget_check"] = metrics.get("global_budget_check")
                details["global_budget_usage"] = metrics.get("global_budget_usage")
        return details
    return {"agent_loop_status": result_payload.get("status")}


def _agent_loop_input_keys(step: StepSpec) -> list[str]:
    keys = [str(key) for key in step.read_keys]
    for key in step.metadata.get("optional_read_keys", []) or []:
        text = str(key)
        if text not in keys:
            keys.append(text)
    return keys


def _agent_loop_metrics_payload(result: Any) -> dict[str, Any]:
    metrics = result.metrics.to_dict()
    trajectory = [dict(item) for item in getattr(result, "trajectory", [])]
    metrics["trajectory_summary"] = {
        "iteration_count": len(trajectory),
        "tool_call_count": len(getattr(result, "tool_calls", []) or []),
        "memory_op_count": len(getattr(result, "memory_ops", []) or []),
        "termination_reason": getattr(result, "termination_reason", None),
        "max_steps_reached": bool(getattr(result, "max_steps_reached", False)),
        "trace_id": getattr(result, "trace_id", None),
    }
    return metrics

def _agent_loop_trace_events(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "event_type": "agent_loop_trajectory",
            "trace_id": getattr(result, "trace_id", None),
            "trace_ref": getattr(result, "trace_ref", None),
            "termination_reason": getattr(result, "termination_reason", None),
            "max_steps_reached": bool(getattr(result, "max_steps_reached", False)),
            "trajectory": [dict(item) for item in getattr(result, "trajectory", [])],
        }
    ]


__all__ = ["AgentLoopStepRunner"]
