"""Join step runner."""

from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._utils import (
    contract_metrics,
    failed_outcome,
    validated_outputs,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)


class JoinStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.JOIN,
        runner_id="builtin.join",
        version="1.0.0",
        supports_checkpoint=False,
        supports_resume=True,
        supports_timeout=False,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Summarizes declared fan-in inputs.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.JOIN:
                raise StepExecutionError(
                    f"unsupported step type for JoinStepRunner: {step.step_type}"
                )

            output_key = str(step.metadata.get("output_key") or "join_result")
            inputs = {
                key: buffer.read(key)
                for key in buffer.list_allowed_reads()
                if buffer.exists(key)
            }
            summary = _join_summary(step, inputs)
            outputs = validated_outputs(
                step,
                {output_key: summary},
                runner_name="join step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, outputs[output_key])
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=contract_metrics(step, started=started, outputs=outputs),
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="JoinStepRunner",
            )


def _join_summary(step: StepSpec, inputs: dict[str, Any]) -> dict[str, Any]:
    strategy = str(
        step.metadata.get("join_policy")
        or step.metadata.get("strategy")
        or step.metadata.get("wait_strategy")
        or "all_success"
    )
    branch_results_key = str(step.metadata.get("branch_results_key") or "")
    branch_results = inputs.get(branch_results_key) if branch_results_key else None
    if not isinstance(branch_results, list):
        branch_results = []
    succeeded_branches = [
        result
        for result in branch_results
        if isinstance(result, dict)
        and result.get("status") == StepStatus.SUCCEEDED.value
    ]
    failed_branches = [
        result
        for result in branch_results
        if isinstance(result, dict)
        and result.get("status") != StepStatus.SUCCEEDED.value
    ]
    required_upstreams = _join_required_upstream_step_ids(step)
    optional_upstreams = _join_optional_upstream_step_ids(step)
    upstream_statuses = _join_upstream_statuses(step, inputs, branch_results)
    succeeded_upstreams = _join_upstreams_by_status(
        upstream_statuses, {StepStatus.SUCCEEDED.value}
    )
    failed_upstreams = _join_upstreams_by_status(
        upstream_statuses,
        {StepStatus.FAILED.value, StepStatus.BLOCKED.value, StepStatus.TIMEOUT.value},
    )
    skipped_upstreams = _join_upstreams_by_status(
        upstream_statuses, {StepStatus.SKIPPED.value}
    )
    missing_upstreams = sorted(
        step_id for step_id in required_upstreams if step_id not in upstream_statuses
    )
    pending_upstreams = sorted(
        step_id
        for step_id in required_upstreams
        if upstream_statuses.get(step_id)
        in {StepStatus.PENDING.value, StepStatus.READY.value, StepStatus.RUNNING.value}
    )
    quorum = int(
        step.metadata.get("quorum")
        or step.metadata.get("join_quorum")
        or len(branch_results)
        or 0
    )
    timed_out = _join_timeout_exceeded(step, inputs)
    on_timeout = str(step.metadata.get("on_timeout") or "fail")

    if not required_upstreams:
        if strategy == "all_success":
            ready = not failed_branches and len(succeeded_branches) == len(
                branch_results
            )
        elif strategy == "any_success":
            ready = bool(succeeded_branches)
        elif strategy == "quorum":
            ready = len(succeeded_branches) >= quorum
        elif strategy == "best_effort":
            ready = bool(branch_results) or bool(inputs)
        elif strategy == "timeout_join":
            ready = (
                bool(inputs)
                if not timed_out
                else on_timeout in {"best_effort", "partial"}
            )
        else:
            raise StepExecutionError(f"unsupported join strategy: {strategy}")
    elif strategy == "all_success":
        ready = not missing_upstreams and not pending_upstreams and not failed_upstreams
    elif strategy == "any_success":
        ready = bool(succeeded_upstreams) and not pending_upstreams
    elif strategy == "quorum":
        ready = len(succeeded_upstreams) >= quorum and not pending_upstreams
    elif strategy == "best_effort":
        ready = not missing_upstreams and not pending_upstreams
    elif strategy == "timeout_join":
        ready = (not missing_upstreams and not pending_upstreams) or (
            timed_out and on_timeout in {"best_effort", "partial"}
        )
    else:
        raise StepExecutionError(f"unsupported join strategy: {strategy}")
    if strategy == "timeout_join" and timed_out and on_timeout == "fail":
        ready = False
    decision = _join_decision(
        ready=ready,
        strategy=strategy,
        timed_out=timed_out,
        on_timeout=on_timeout,
        failed_upstreams=failed_upstreams,
        missing_upstreams=missing_upstreams,
        pending_upstreams=pending_upstreams,
    )
    return {
        "strategy": strategy,
        "join_policy": strategy,
        "ready": ready,
        "decision": decision,
        "joined_keys": sorted(inputs),
        "inputs": inputs,
        "branch_count": len(branch_results),
        "succeeded_branch_count": len(succeeded_branches),
        "failed_branch_count": len(failed_branches),
        "quorum": quorum if strategy == "quorum" else None,
        "required_upstream_step_ids": required_upstreams,
        "optional_upstream_step_ids": optional_upstreams,
        "succeeded_upstreams": succeeded_upstreams,
        "failed_upstreams": failed_upstreams,
        "missing_upstreams": missing_upstreams,
        "skipped_upstreams": skipped_upstreams,
        "pending_upstreams": pending_upstreams,
        "timed_out": timed_out,
        "on_timeout": on_timeout if strategy == "timeout_join" else None,
    }


def _join_required_upstream_step_ids(step: StepSpec) -> list[str]:
    raw = (
        step.metadata.get("required_upstream_step_ids")
        or step.metadata.get("upstream_step_ids")
        or []
    )
    if not isinstance(raw, list):
        raise StepExecutionError("join required_upstream_step_ids must be a list")
    return [str(item) for item in raw]


def _join_optional_upstream_step_ids(step: StepSpec) -> list[str]:
    raw = step.metadata.get("optional_upstream_step_ids") or []
    if not isinstance(raw, list):
        raise StepExecutionError("join optional_upstream_step_ids must be a list")
    return [str(item) for item in raw]


def _join_upstream_statuses(
    step: StepSpec,
    inputs: dict[str, Any],
    branch_results: list[dict[str, Any]],
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    raw_statuses = inputs.get(
        str(step.metadata.get("upstream_statuses_key") or "upstream_statuses")
    )
    if isinstance(raw_statuses, dict):
        statuses.update({str(key): str(value) for key, value in raw_statuses.items()})
    for step_id in [
        *_join_required_upstream_step_ids(step),
        *_join_optional_upstream_step_ids(step),
    ]:
        key = f"{step_id}_status"
        if key in inputs:
            statuses[step_id] = str(inputs[key])
    for result in branch_results:
        if not isinstance(result, dict):
            continue
        branch_id = result.get("branch_id")
        status = result.get("status")
        if branch_id is not None and status is not None:
            statuses[str(branch_id)] = str(status)
    return statuses


def _join_upstreams_by_status(
    upstream_statuses: dict[str, str],
    statuses: set[str],
) -> list[str]:
    return sorted(
        step_id for step_id, status in upstream_statuses.items() if status in statuses
    )


def _join_timeout_exceeded(step: StepSpec, inputs: dict[str, Any]) -> bool:
    if (
        str(step.metadata.get("join_policy") or step.metadata.get("strategy") or "")
        != "timeout_join"
    ):
        return False
    timeout_seconds = step.metadata.get("timeout_seconds")
    if timeout_seconds is None:
        return False
    started_at = inputs.get(
        "join_wait_started_at", step.metadata.get("join_wait_started_at")
    )
    if started_at is None:
        return False
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise StepExecutionError(f"invalid join_wait_started_at: {started_at}") from exc
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
    return elapsed >= float(timeout_seconds)


def _join_decision(
    *,
    ready: bool,
    strategy: str,
    timed_out: bool,
    on_timeout: str,
    failed_upstreams: list[str],
    missing_upstreams: list[str],
    pending_upstreams: list[str],
) -> str:
    if strategy == "timeout_join" and timed_out:
        if on_timeout in {"best_effort", "partial"} and ready:
            return "partial_join"
        return "timeout"
    if ready:
        return "joined"
    if failed_upstreams:
        return "failed_upstream"
    if missing_upstreams or pending_upstreams:
        return "waiting"
    return "not_ready"

__all__ = ["JoinStepRunner"]


