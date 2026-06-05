from __future__ import annotations

import json
import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.artifacts import ArtifactManager
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
from framework.workflow.runners.registry import StepRunnerRegistry


class SubworkflowStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.SUBWORKFLOW,
        runner_id="builtin.subworkflow",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["workflow_executor"],
        description="Runs a child WorkflowSpec as a subworkflow.",
    )

    def __init__(
        self,
        workflow_registry: dict[str, Any],
        step_runner_registry: StepRunnerRegistry,
        *,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._workflow_registry = dict(workflow_registry)
        self._step_runner_registry = step_runner_registry
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._global_budget_tracker: Any | None = None

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def configure_global_budget_tracker(
        self, global_budget_tracker: Any | None
    ) -> None:
        self._global_budget_tracker = global_budget_tracker

    def can_resolve(self, step: StepSpec) -> bool:
        if step.step_type != StepType.SUBWORKFLOW:
            return False
        if not self._workflow_registry:
            return True
        workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
        return workflow_id in self._workflow_registry

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.metadata.get("workflow_id") or step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="subworkflow_missing_workflow_id",
                message="Subworkflow step requires metadata.workflow_id or implementation.",
                field="metadata.workflow_id",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.SUBWORKFLOW:
                raise StepExecutionError(
                    f"unsupported step type for SubworkflowStepRunner: {step.step_type}"
                )
            if self._artifact_manager is None or self._run_id is None:
                raise StepExecutionError("SubworkflowStepRunner requires run context")
            parent_run_id = self._run_id

            workflow_id = str(step.metadata.get("workflow_id") or step.implementation)
            try:
                workflow = self._workflow_registry[workflow_id]
            except KeyError as exc:
                raise StepExecutionError(
                    f"subworkflow is not registered: {workflow_id}"
                ) from exc

            request = _subworkflow_request(step, buffer)

            from framework.workflow.runtime.executor import WorkflowExecutor

            child_run_id = str(
                step.metadata.get("child_run_id")
                or f"{self._run_id}.{step.step_id}.{workflow.workflow_id}"
            )
            executor = WorkflowExecutor(
                function_step_runner=None,
                step_runner_registry=self._step_runner_registry,
                artifact_manager=self._artifact_manager,
                global_budget_tracker=(
                    self._global_budget_tracker
                    if _subworkflow_inherits_budget(step)
                    else None
                ),
            )
            result = executor.execute(
                workflow,
                request,
                profile=str(step.metadata.get("profile") or "subworkflow"),
                run_id=child_run_id,
            )
            _record_child_manifest_parent_link(
                artifact_manager=self._artifact_manager,
                child_run_id=child_run_id,
                parent_run_id=parent_run_id,
                parent_step_id=step.step_id,
            )
            metrics = _subworkflow_metrics(
                child_run_id=child_run_id,
                workflow_id=workflow.workflow_id,
                workflow_version=workflow.version,
                result=result,
            )
            metrics["failure_propagation"] = _subworkflow_failure_propagation(step)
            metrics["budget_scope"] = _subworkflow_budget_scope(step)
            metrics["inherit_budget"] = _subworkflow_inherits_budget(step)
            metrics["cancellation_policy"] = _subworkflow_cancellation_policy(step)
            output_key = str(step.metadata.get("output_key") or "subworkflow_result")
            child_run_record = _subworkflow_child_run_record(
                step=step,
                child_run_id=child_run_id,
                workflow=workflow,
                result=result,
            )
            raw_outputs = {
                output_key: result.to_dict(),
                **_subworkflow_optional_outputs(
                    step=step,
                    child_run_record=child_run_record,
                    result=result,
                ),
                **_subworkflow_mapped_outputs(step, result.output),
            }
            if result.status.value != "succeeded":
                raw_outputs.update(
                    _subworkflow_failure_policy_outputs(
                        step=step,
                        result=result,
                    )
                )
            outputs = _validated_outputs(
                step,
                raw_outputs,
                runner_name="subworkflow step",
                allow_missing_required=result.status.value != "succeeded",
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    buffer.write(key, value, lineage={"step_id": step.step_id})
            metrics = _with_contract_metrics(
                metrics,
                step,
                started=started,
                outputs=outputs,
                artifact_count=int(metrics.get("child_artifact_count") or 0),
            )
            lineage = [
                {
                    "type": "subworkflow",
                    "parent_run_id": self._run_id,
                    "child_run_id": child_run_id,
                    "workflow_id": workflow.workflow_id,
                    "workflow_version": workflow.version,
                    "manifest_path": result.manifest_path,
                    "cancellation_policy": _subworkflow_cancellation_policy(step),
                }
            ]
            if result.status.value == "succeeded":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=metrics,
                    lineage=lineage,
                )
            return _subworkflow_failure_outcome(
                step=step,
                workflow_id=workflow_id,
                result=result,
                outputs=outputs,
                metrics=metrics,
                lineage=lineage,
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="SubworkflowStepRunner",
            )


def _subworkflow_request(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> dict[str, Any]:
    input_map = step.metadata.get("input_map")
    if isinstance(input_map, dict):
        request = {}
        for target_key, source_key in input_map.items():
            request[str(target_key)] = buffer.read(str(source_key))
        return request

    request = step.metadata.get("request")
    request_key = step.metadata.get("request_key")
    if request_key is not None:
        request = buffer.read(str(request_key))
    if request is None:
        request = {}
    if not isinstance(request, dict):
        raise StepExecutionError(
            f"subworkflow step {step.step_id} request must be an object"
        )
    return dict(request)


def _subworkflow_mapped_outputs(
    step: StepSpec, child_output: dict[str, Any]
) -> dict[str, Any]:
    output_map = step.metadata.get("output_map")
    if not isinstance(output_map, dict):
        return {}
    outputs = {}
    for parent_key, child_key in output_map.items():
        key = str(child_key)
        if key in child_output:
            outputs[str(parent_key)] = child_output[key]
    return outputs


def _subworkflow_optional_outputs(
    *,
    step: StepSpec,
    child_run_record: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    declared = set(step.write_keys)
    if "child_runs" in declared:
        outputs["child_runs"] = [child_run_record]
    if "subworkflow_event_summary" in declared:
        outputs["subworkflow_event_summary"] = _subworkflow_event_summary(result)
    if "subworkflow_cancellation_policy" in declared:
        outputs["subworkflow_cancellation_policy"] = _subworkflow_cancellation_policy(
            step
        )
    return outputs


def _record_child_manifest_parent_link(
    *,
    artifact_manager: ArtifactManager,
    child_run_id: str,
    parent_run_id: str,
    parent_step_id: str,
) -> None:
    manifest_path = artifact_manager.run_dir(child_run_id) / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    manifest["parent_run_id"] = parent_run_id
    manifest["parent_step_id"] = parent_step_id
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _subworkflow_child_run_record(
    *,
    step: StepSpec,
    child_run_id: str,
    workflow: Any,
    result: Any,
) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "child_run_id": child_run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow.version,
        "status": result.status.value,
        "manifest_path": result.manifest_path,
    }


def _subworkflow_event_summary(result: Any) -> dict[str, Any]:
    manifest = dict(result.manifest) if isinstance(result.manifest, dict) else {}
    raw_metrics = manifest.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    failed_step_id = result.error.step_id if result.error else None
    return {
        "event_count": int(
            metrics.get("event_count") or manifest.get("event_count") or 0
        ),
        "failed_step_id": failed_step_id,
        "status": result.status.value,
        "path": list(result.path),
    }


def _subworkflow_failure_propagation(step: StepSpec) -> str:
    return str(step.metadata.get("failure_propagation") or "fail_parent")


def _subworkflow_inherits_budget(step: StepSpec) -> bool:
    return bool(step.metadata.get("inherit_budget", False))


def _subworkflow_budget_scope(step: StepSpec) -> str:
    return str(
        step.metadata.get("budget_scope")
        or ("shared" if _subworkflow_inherits_budget(step) else "isolated")
    )


def _subworkflow_cancellation_policy(step: StepSpec) -> dict[str, Any]:
    raw_policy = step.metadata.get("cancellation_policy")
    if isinstance(raw_policy, dict):
        policy = dict(raw_policy)
    else:
        policy = {}
    policy.setdefault("cascade", bool(step.metadata.get("cascade_cancel", True)))
    return policy


def _subworkflow_failure_outcome(
    *,
    step: StepSpec,
    workflow_id: str,
    result: Any,
    outputs: dict[str, Any],
    metrics: dict[str, Any],
    lineage: list[dict[str, Any]],
) -> StepOutcome:
    policy = _subworkflow_failure_propagation(step)
    error_type = result.error.error_type if result.error else "SubworkflowFailed"
    error_message = (
        result.error.message if result.error else f"subworkflow failed: {workflow_id}"
    )
    error_details = {
        "child_run_id": metrics.get("child_run_id"),
        "child_status": result.status.value,
        "failure_propagation": policy,
    }
    if policy == "block_parent":
        return StepOutcome(
            status=StepStatus.BLOCKED,
            outputs=outputs,
            error_type=error_type,
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
        )
    if policy == "best_effort":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowPartialFailure",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="best_effort",
        )
    if policy == "fallback_output":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowFallbackUsed",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="fallback_output",
        )
    if policy == "isolate_failure":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            error_type="SubworkflowFailureIsolated",
            error_message=error_message,
            error_details=error_details,
            metrics=metrics,
            lineage=lineage,
            next_hint="isolate_failure",
        )
    return StepOutcome(
        status=StepStatus.FAILED,
        outputs=outputs,
        error_type=error_type,
        error_message=error_message,
        error_details=error_details,
        metrics=metrics,
        lineage=lineage,
    )


def _subworkflow_failure_policy_outputs(
    *,
    step: StepSpec,
    result: Any,
) -> dict[str, Any]:
    policy = _subworkflow_failure_propagation(step)
    error_type = result.error.error_type if result.error else "SubworkflowFailed"
    error_message = result.error.message if result.error else "subworkflow failed"
    outputs: dict[str, Any] = {}
    if policy == "best_effort":
        outputs["partial_success"] = True
        outputs["child_failure"] = {
            "error_type": error_type,
            "error_message": error_message,
            "status": result.status.value,
        }
    elif policy == "fallback_output":
        fallback_output = step.metadata.get("fallback_output")
        if isinstance(fallback_output, dict):
            outputs.update(fallback_output)
    elif policy == "isolate_failure":
        outputs["child_failure"] = {
            "error_type": error_type,
            "error_message": error_message,
            "status": result.status.value,
        }
    return outputs


def _subworkflow_metrics(
    *,
    child_run_id: str,
    workflow_id: str,
    workflow_version: str,
    result: Any,
) -> dict[str, Any]:
    manifest = result.manifest or {}
    workflow_metrics = manifest.get("metrics") or {}
    return {
        "child_run_id": child_run_id,
        "child_workflow_id": workflow_id,
        "child_workflow_version": workflow_version,
        "child_status": result.status.value,
        "child_step_count": int(manifest.get("step_count") or len(result.step_results)),
        "child_artifact_count": int(
            workflow_metrics.get("artifact_count")
            or len(manifest.get("artifacts") or {})
        ),
        "child_event_count": int(
            workflow_metrics.get("event_count") or manifest.get("event_count") or 0
        ),
        "child_manifest_path": result.manifest_path,
        "child_events_path": result.events_path,
    }


__all__ = ["SubworkflowStepRunner"]
