from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256
import math
import re
import time
from typing import Any

from framework.shared.attempts import (
    AttemptContext,
    AttemptIndeterminateError,
    AttemptOutcome,
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
    bind_attempt_context,
    current_attempt_context,
    derive_idempotency_key,
)
from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import DataBuffer, StepScopedDataBufferView
from framework.agent.artifacts import ArtifactManager
from framework.agent.artifacts import ArtifactRef as StorageArtifactRef
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
    default_runner_can_resolve,
    ensure_attempt_active,
)
from framework.workflow.runners.function import FunctionStepRegistry

_PARALLEL_CONFLICT_STRATEGIES = {
    "error",
    "namespace",
    "last_write",
    "first_wins",
    "last_wins",
    "merge_list",
    "merge_dict",
}
_PARALLEL_FAILURE_STRATEGIES = {
    "fail_fast",
    "best_effort",
    "all_success",
    "min_success",
}
_BRANCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class _ParallelBranchExecutionError(Exception):
    def __init__(self, original_error: Exception, *, attempts: int) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.attempts = attempts


class ParallelGroupStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.PARALLEL_GROUP,
        runner_id="builtin.parallel_group",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        # Branch implementations are arbitrary application functions. Treat
        # the aggregate as externally effectful unless the Step supplies an
        # explicit idempotency and reconciliation contract.
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["function_registry"],
        description="Runs in-process function branches concurrently.",
    )

    def __init__(
        self,
        function_registry: FunctionStepRegistry,
        *,
        max_workers: int = 4,
        artifact_manager: ArtifactManager | None = None,
        run_id: str | None = None,
    ) -> None:
        self._function_registry = function_registry
        self._max_workers = max(1, max_workers)
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        branches = step.metadata.get("branches")
        if isinstance(branches, list) and branches:
            return []
        return [
            ValidationErrorItem(
                code="parallel_group_missing_branches",
                message="Parallel group step requires non-empty metadata.branches.",
                field="metadata.branches",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            ensure_attempt_active()
            if step.step_type != StepType.PARALLEL_GROUP:
                raise StepExecutionError(
                    f"unsupported step type for ParallelGroupStepRunner: {step.step_type}"
                )
            branches = step.metadata.get("branches")
            if not isinstance(branches, list) or not branches:
                raise StepExecutionError(
                    f"parallel_group step {step.step_id} requires branches"
                )
            normalized_branches = _normalize_parallel_branches(
                branches, step_id=step.step_id
            )
            normalized_branches = [
                {
                    **branch,
                    "_retry_safe": _parallel_branch_retry_is_safe(step, branch),
                }
                for branch in normalized_branches
            ]

            branch_results: list[dict[str, Any]] = []
            failed_branch_results: list[dict[str, Any]] = []
            merged_outputs: dict[str, Any] = {}
            conflict_strategy = str(step.metadata.get("conflict_strategy") or "error")
            failure_strategy = str(step.metadata.get("failure_strategy") or "fail_fast")
            if conflict_strategy not in _PARALLEL_CONFLICT_STRATEGIES:
                raise StepExecutionError(
                    f"unsupported parallel conflict strategy: {conflict_strategy}"
                )
            if failure_strategy not in _PARALLEL_FAILURE_STRATEGIES:
                raise StepExecutionError(
                    f"unsupported parallel failure strategy: {failure_strategy}"
                )
            min_success = int(
                step.metadata.get("min_success")
                or step.metadata.get("success_threshold")
                or 1
            )
            namespace_key = str(step.metadata.get("namespace_key") or "")
            max_workers = min(self._max_workers, len(normalized_branches))
            pool = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="news-workflow-parallel",
            )
            try:
                branch_results, failed_branch_results = (
                    _run_parallel_branches_with_policy(
                        pool=pool,
                        registry=self._function_registry,
                        branches=normalized_branches,
                        parent_buffer=buffer,
                        failure_strategy=failure_strategy,
                    )
                )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            ensure_attempt_active()
            _enforce_parallel_failure_strategy(
                failure_strategy=failure_strategy,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
                min_success=min_success,
            )
            if conflict_strategy == "namespace":
                namespace_key = namespace_key or "branches"
            else:
                for branch_result in branch_results:
                    _merge_parallel_outputs(
                        merged_outputs,
                        branch_result["outputs"],
                        conflict_strategy=conflict_strategy,
                        step_id=step.step_id,
                    )

            ensure_attempt_active()
            branch_artifacts = _publish_parallel_branch_artifacts(
                artifact_manager=self._artifact_manager,
                run_id=self._run_id,
                step=step,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
            )
            outputs = _parallel_group_outputs(
                step,
                merged_outputs=merged_outputs,
                branch_results=branch_results,
                failed_branch_results=failed_branch_results,
                namespace_key=namespace_key,
            )
            outputs = _validated_outputs(
                step, outputs, runner_name="parallel_group step"
            )
            for key, value in outputs.items():
                if key in buffer.list_allowed_writes():
                    ensure_attempt_active()
                    buffer.write(
                        key,
                        value,
                        lineage={"step_id": step.step_id, "parallel_group": True},
                    )
            metrics = _with_contract_metrics(
                _parallel_group_metrics(
                    branches=normalized_branches,
                    branch_results=branch_results,
                    failed_branch_results=failed_branch_results,
                    conflict_strategy=conflict_strategy,
                    failure_strategy=failure_strategy,
                    min_success=min_success,
                    max_workers=self._max_workers,
                    output_keys=list(outputs),
                ),
                step,
                started=started,
                outputs=outputs,
            )
            if failed_branch_results and failure_strategy == "best_effort":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    error_type="ParallelGroupPartialFailure",
                    error_message=(
                        f"{len(failed_branch_results)} parallel branch(es) failed"
                    ),
                    error_details={"failed_branches": failed_branch_results},
                    metrics=metrics,
                    artifacts=branch_artifacts,
                    lineage=_parallel_group_lineage(step, branch_results),
                    next_hint="best_effort",
                )
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=metrics,
                artifacts=branch_artifacts,
                lineage=_parallel_group_lineage(step, branch_results),
            )
        except Exception as exc:
            return _failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ParallelGroupStepRunner",
            )


def _run_parallel_branch(
    registry: FunctionStepRegistry,
    branch: Any,
    parent_buffer: StepScopedDataBufferView,
) -> dict[str, Any]:
    ensure_attempt_active()
    branch = _normalize_parallel_branch(branch, index=0)
    started_at = _utc_now_iso()
    started = time.perf_counter()
    attempts = int(branch.get("_attempts") or 1)
    branch_id = str(branch["branch_id"])
    implementation = str(branch.get("implementation") or "")
    read_keys = [str(key) for key in branch.get("read_keys", [])]
    write_keys = [str(key) for key in branch.get("write_keys", [])]
    required_output_keys = [str(key) for key in branch.get("required_output_keys", [])]

    local_values = {
        key: parent_buffer.read(key)
        for key in read_keys
        if key in parent_buffer.list_allowed_reads() and parent_buffer.exists(key)
    }
    local_buffer = DataBuffer(local_values)
    scoped = local_buffer.scope(read_keys=read_keys, write_keys=write_keys)
    ensure_attempt_active()
    raw_outputs = registry.get(implementation)(scoped) or {}
    ensure_attempt_active()
    if not isinstance(raw_outputs, dict):
        raise StepExecutionError(
            f"parallel_group branch {branch_id or implementation} returned "
            f"{type(raw_outputs).__name__}, expected dict"
        )
    missing = sorted(set(required_output_keys) - set(raw_outputs))
    if missing:
        raise StepExecutionError(
            f"parallel_group branch {branch_id or implementation} missing required outputs: "
            f"{', '.join(missing)}"
        )
    return {
        "branch_id": branch_id or implementation,
        "implementation": implementation,
        "status": StepStatus.SUCCEEDED.value,
        "outputs": raw_outputs,
        "attempts": attempts,
        "duration_ms": _elapsed_ms(started),
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "error_type": None,
        "error_message": None,
        "artifact_refs": [],
        "lineage": _parallel_branch_lineage(
            step_id=str(branch.get("_step_id") or ""),
            branch_id=branch_id,
            output_keys=sorted(str(key) for key in raw_outputs),
        ),
    }


def _branch_id(branch: dict[str, Any], *, index: int) -> str:
    raw_branch_id = branch.get("branch_id")
    raw_implementation = branch.get("implementation")
    candidate = raw_branch_id if raw_branch_id is not None else raw_implementation
    branch_id = str(candidate or "").strip()
    if not branch_id:
        raise StepExecutionError(
            f"parallel_group branch at index {index} requires branch_id or implementation"
        )
    if not _BRANCH_ID_PATTERN.fullmatch(branch_id):
        raise StepExecutionError(
            "parallel_group branch_id must contain only letters, digits, '_', '-', or '.'"
        )
    return branch_id


def _normalize_parallel_branch(
    branch: Any,
    *,
    index: int,
    step_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(branch, dict):
        raise StepExecutionError("parallel_group branch must be an object")
    implementation = str(branch.get("implementation") or "").strip()
    if not implementation:
        raise StepExecutionError("parallel_group branch implementation is required")
    normalized = dict(branch)
    normalized["implementation"] = implementation
    normalized["branch_id"] = _branch_id(normalized, index=index)
    if step_id is not None:
        normalized["_step_id"] = step_id
    return normalized


def _normalize_parallel_branches(
    branches: list[Any],
    *,
    step_id: str,
) -> list[dict[str, Any]]:
    normalized_branches = [
        _normalize_parallel_branch(branch, index=index, step_id=step_id)
        for index, branch in enumerate(branches)
    ]
    seen: dict[str, int] = {}
    for index, branch in enumerate(normalized_branches):
        branch_id = str(branch["branch_id"])
        if branch_id in seen:
            raise StepExecutionError(
                f"parallel_group branch_id must be unique: {branch_id}"
            )
        seen[branch_id] = index
    return normalized_branches


def _parallel_branch_failure_result(
    branch: dict[str, Any],
    exc: Exception,
    *,
    attempts: int | None = None,
    started_at: str | None = None,
    started: float | None = None,
) -> dict[str, Any]:
    original_error = (
        exc.original_error if isinstance(exc, _ParallelBranchExecutionError) else exc
    )
    actual_attempts = (
        exc.attempts if isinstance(exc, _ParallelBranchExecutionError) else attempts
    )
    branch_id = str(branch.get("branch_id") or "")
    return {
        "branch_id": branch_id,
        "implementation": str(branch.get("implementation") or ""),
        "status": StepStatus.FAILED.value,
        "outputs": {},
        "error_type": type(original_error).__name__,
        "error_message": str(original_error),
        "attempts": int(actual_attempts or branch.get("_attempts") or 1),
        "duration_ms": _elapsed_ms(started) if started is not None else 0.0,
        "started_at": started_at or _utc_now_iso(),
        "finished_at": _utc_now_iso(),
        "artifact_refs": [],
        "lineage": _parallel_branch_lineage(
            step_id=str(branch.get("_step_id") or ""),
            branch_id=branch_id,
            output_keys=[],
        ),
    }


def _run_parallel_branches_with_policy(
    *,
    pool: ThreadPoolExecutor,
    registry: FunctionStepRegistry,
    branches: list[dict[str, Any]],
    parent_buffer: StepScopedDataBufferView,
    failure_strategy: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    branch_results: list[dict[str, Any]] = []
    failed_branch_results: list[dict[str, Any]] = []
    pending: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    start_times: dict[Future[dict[str, Any]], float] = {}
    started_at_by_future: dict[Future[dict[str, Any]], str] = {}
    attempt_context = current_attempt_context()
    execution_limits = (
        attempt_context.execution_limits
        if attempt_context is not None
        and attempt_context.execution_limits is not None
        else ExecutionLimits(
            execution_id="standalone:parallel-group",
            retry_credits=RetryCreditLedger(
                max_total_retries=sum(_branch_max_retries(branch) for branch in branches)
            ),
        )
    )

    for branch in branches:
        submitted_branch = _branch_with_attempt(branch, 1)
        future = pool.submit(
            _run_parallel_branch_with_context,
            registry,
            submitted_branch,
            parent_buffer,
            attempt_context,
            execution_limits,
        )
        pending[future] = submitted_branch
        start_times[future] = time.perf_counter()
        started_at_by_future[future] = _utc_now_iso()

    while pending:
        done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
        for future in done:
            branch = pending.pop(future)
            start_times.pop(future, None)
            started_at_by_future.pop(future, None)
            try:
                branch_result = future.result()
            except Exception as exc:
                if failure_strategy in {"fail_fast", "all_success"}:
                    raise
                failed_branch_results.append(
                    _parallel_branch_failure_result(branch, exc)
                )
                continue
            branch_results.append(branch_result)
    return branch_results, failed_branch_results


def _run_parallel_branch_with_context(
    registry: FunctionStepRegistry,
    branch: dict[str, Any],
    parent_buffer: StepScopedDataBufferView,
    attempt_context: AttemptContext | None,
    execution_limits: ExecutionLimits,
) -> dict[str, Any]:
    if attempt_context is None:
        return _run_parallel_branch_with_policy(
            registry,
            branch,
            parent_buffer,
            execution_limits=execution_limits,
        )
    with bind_attempt_context(attempt_context):
        return _run_parallel_branch_with_policy(
            registry,
            branch,
            parent_buffer,
            execution_limits=execution_limits,
        )


def _run_parallel_branch_with_policy(
    registry: FunctionStepRegistry,
    branch: dict[str, Any],
    parent_buffer: StepScopedDataBufferView,
    *,
    execution_limits: ExecutionLimits,
) -> dict[str, Any]:
    max_retries = _branch_max_retries(branch)
    retry_on_error_types = _branch_retry_on_error_types(branch)
    no_retry_on_error_types = _branch_no_retry_on_error_types(branch)
    parent_context = current_attempt_context()
    local_budget = LocalRetryBudget(max_attempts=max_retries + 1)
    branch_key = (
        derive_idempotency_key(
            parent_context.idempotency_key,
            "branch",
            str(branch["branch_id"]),
        )
        if parent_context is not None
        else f"parallel-branch:{branch['branch_id']}"
    )
    admission_policy = _branch_admission_policy(branch)
    supervisor = AttemptSupervisor(
        cancellation_grace_seconds=admission_policy.cancellation_grace_seconds
    )

    def finalize_branch_attempt(
        outcome: AttemptOutcome[dict[str, Any]],
    ) -> AttemptOutcome[dict[str, Any]]:
        if bool(branch.get("_retry_safe")):
            return outcome
        if outcome.state is AttemptState.TIMED_OUT:
            return replace(
                outcome,
                indeterminate=True,
                reason_code=(
                    outcome.reason_code or "parallel_branch_timeout_indeterminate"
                ),
            )
        if outcome.state is AttemptState.FAILED:
            return replace(
                outcome,
                state=AttemptState.INDETERMINATE,
                indeterminate=True,
                reason_code="parallel_branch_effect_indeterminate",
            )
        return outcome

    while local_budget.remaining > 0:
        candidate_attempt = local_budget.used + 1
        attempt_branch = _branch_with_attempt(branch, candidate_attempt)
        outcome = supervisor.run(
            lambda: _run_parallel_branch(
                registry,
                attempt_branch,
                parent_buffer,
            ),
            timeout_seconds=admission_policy.timeout_seconds,
            idempotency_key=branch_key,
            operation_id=branch_key,
            operation_kind="parallel_branch",
            local_budget=local_budget,
            admission_policy=admission_policy,
            execution_limits=execution_limits,
            parent_context=parent_context,
            finalize=finalize_branch_attempt,
        )
        if outcome.state is AttemptState.REJECTED:
            error = outcome.error or StepExecutionError(
                "parallel branch admission rejected without an error"
            )
            raise _ParallelBranchExecutionError(
                error,
                attempts=local_budget.used,
            ) from error
        if outcome.context is None:
            raise RuntimeError("started parallel branch is missing attempt context")
        attempts = outcome.context.local_attempt_no
        if outcome.state is AttemptState.SUCCEEDED:
            return outcome.value

        error = outcome.error
        if outcome.state is AttemptState.INDETERMINATE:
            error = error or AttemptIndeterminateError(outcome.context.attempt_id)
        elif outcome.state is AttemptState.TIMED_OUT:
            error = TimeoutError(
                f"parallel_group branch {branch['branch_id']} exceeded timeout of "
                f"{_branch_timeout_text(admission_policy.timeout_seconds)}"
            )
        elif error is None:
            error = StepExecutionError("parallel branch failed without an error")

        indeterminate = (
            outcome.indeterminate
            or outcome.state is AttemptState.INDETERMINATE
            or not bool(branch.get("_retry_safe"))
        )
        if indeterminate:
            if parent_context is not None:
                if not outcome.termination_confirmed:
                    parent_context.mark_descendant_unconfirmed()
                else:
                    parent_context.mark_descendant_indeterminate()
            raise _ParallelBranchExecutionError(error, attempts=attempts) from error
        if (
            local_budget.remaining == 0
            or not _should_retry_branch_error(
                error,
                retry_on_error_types=retry_on_error_types,
                no_retry_on_error_types=no_retry_on_error_types,
            )
        ):
            raise _ParallelBranchExecutionError(error, attempts=attempts) from error
        delay = _branch_retry_delay_seconds(branch, attempts)
        if delay > 0:
            time.sleep(delay)
    raise RuntimeError("parallel branch retry loop exited unexpectedly")


def _branch_with_attempt(branch: dict[str, Any], attempts: int) -> dict[str, Any]:
    return {**branch, "_attempts": attempts}


def _parallel_branch_retry_is_safe(
    step: StepSpec,
    branch: dict[str, Any],
) -> bool:
    side_effect_level = str(
        branch.get("side_effect_level") or StepRunnerSideEffectLevel.EXTERNAL_WRITE
    )
    if side_effect_level in {
        StepRunnerSideEffectLevel.NONE.value,
        StepRunnerSideEffectLevel.READ_ONLY.value,
    }:
        return True
    if side_effect_level == StepRunnerSideEffectLevel.IDEMPOTENT_WRITE.value:
        return bool(branch.get("idempotent") is True or step.idempotent)
    return bool(
        (
            branch.get("idempotency_contract") is True
            or step.metadata.get("idempotency_contract") is True
        )
        and (
            branch.get("reconciliation_supported") is True
            or step.metadata.get("reconciliation_supported") is True
        )
    )


def _branch_timeout_seconds(branch: dict[str, Any]) -> float | None:
    value = branch.get("timeout_seconds")
    if value is None:
        return None
    if isinstance(value, bool):
        raise StepExecutionError(
            "parallel_group branch timeout_seconds must be a finite positive number"
        )
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise StepExecutionError(
            "parallel_group branch timeout_seconds must be a finite positive number"
        )
    return timeout


def _branch_admission_policy(
    branch: dict[str, Any],
) -> DeadlineAdmissionPolicy:
    timeout = _branch_timeout_seconds(branch)
    min_start_window = _branch_non_negative_window(
        branch,
        "min_start_window_seconds",
        default=0.0,
    )
    cancellation_grace = _branch_non_negative_window(
        branch,
        "cancellation_grace_seconds",
        default=0.0,
    )
    completion_reserve = _branch_non_negative_window(
        branch,
        "completion_reserve_seconds",
        default=0.0,
    )
    return DeadlineAdmissionPolicy(
        timeout_seconds=timeout,
        min_start_window_seconds=min_start_window,
        cancellation_grace_seconds=cancellation_grace,
        completion_reserve_seconds=completion_reserve,
        admission_details={"branch_id": str(branch["branch_id"])},
    )


def _branch_non_negative_window(
    branch: dict[str, Any],
    field_name: str,
    *,
    default: float,
) -> float:
    raw = branch.get(field_name, default)
    if isinstance(raw, bool):
        raise StepExecutionError(
            f"parallel_group branch {field_name} must be finite and non-negative"
        )
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise StepExecutionError(
            f"parallel_group branch {field_name} must be finite and non-negative"
        )
    return value


def _branch_timeout_text(timeout_seconds: float | None) -> str:
    if timeout_seconds is None:
        return "its effective deadline"
    return f"{timeout_seconds:g} seconds"


def _branch_retry_policy(branch: dict[str, Any]) -> dict[str, Any]:
    policy = branch.get("retry_policy")
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise StepExecutionError("parallel_group branch retry_policy must be an object")
    return dict(policy)


def _branch_max_retries(branch: dict[str, Any]) -> int:
    policy = _branch_retry_policy(branch)
    max_retries = int(policy.get("max_retries") or 0)
    if max_retries < 0:
        raise StepExecutionError(
            "parallel_group branch max_retries must be non-negative"
        )
    return max_retries


def _branch_retry_delay_seconds(branch: dict[str, Any], attempt: int) -> float:
    policy = _branch_retry_policy(branch)
    raw_delays = policy.get("retry_delay_seconds") or []
    if not isinstance(raw_delays, list):
        raise StepExecutionError(
            "parallel_group branch retry_delay_seconds must be a list"
        )
    if not raw_delays:
        return 0.0
    index = min(max(attempt - 1, 0), len(raw_delays) - 1)
    delay = float(raw_delays[index])
    if not math.isfinite(delay) or delay < 0:
        raise StepExecutionError(
            "parallel_group branch retry delay must be finite and non-negative"
        )
    return delay


def _branch_retry_on_error_types(branch: dict[str, Any]) -> set[str]:
    policy = _branch_retry_policy(branch)
    values = policy.get("retry_on_error_types") or []
    if not isinstance(values, list):
        raise StepExecutionError(
            "parallel_group branch retry_on_error_types must be a list"
        )
    return {str(value) for value in values}


def _branch_no_retry_on_error_types(branch: dict[str, Any]) -> set[str]:
    policy = _branch_retry_policy(branch)
    values = policy.get("no_retry_on_error_types") or []
    if not isinstance(values, list):
        raise StepExecutionError(
            "parallel_group branch no_retry_on_error_types must be a list"
        )
    return {str(value) for value in values}


def _should_retry_branch_error(
    exc: Exception,
    *,
    retry_on_error_types: set[str],
    no_retry_on_error_types: set[str],
) -> bool:
    error_type = type(exc).__name__
    if error_type in no_retry_on_error_types:
        return False
    if retry_on_error_types and error_type not in retry_on_error_types:
        return False
    return True


def _parallel_group_outputs(
    step: StepSpec,
    *,
    merged_outputs: dict[str, Any],
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    namespace_key: str,
) -> dict[str, Any]:
    outputs = dict(merged_outputs)
    if namespace_key:
        outputs[namespace_key] = {
            str(result["branch_id"]): result["outputs"] for result in branch_results
        }
    declared_write_keys = set(step.write_keys)
    result_key = str(
        step.metadata.get("branch_results_key")
        or ("branch_results" if "branch_results" in declared_write_keys else "")
    )
    failed_result_key = str(
        step.metadata.get("failed_branch_results_key")
        or (
            "failed_branch_results"
            if "failed_branch_results" in declared_write_keys
            else ""
        )
    )
    if result_key:
        result_items = (
            list(branch_results)
            if failed_result_key and failed_result_key != result_key
            else [*branch_results, *failed_branch_results]
        )
        outputs[result_key] = result_items
    if failed_result_key and failed_result_key != result_key:
        outputs[failed_result_key] = list(failed_branch_results)
    if "success_count" in declared_write_keys:
        outputs["success_count"] = len(branch_results)
    if "failure_count" in declared_write_keys:
        outputs["failure_count"] = len(failed_branch_results)
    if "partial_success" in declared_write_keys:
        outputs["partial_success"] = bool(failed_branch_results)
    summary_key = str(step.metadata.get("summary_key") or "")
    if summary_key:
        outputs[summary_key] = {
            "branch_count": len(branch_results) + len(failed_branch_results),
            "succeeded_branch_count": len(branch_results),
            "failed_branch_count": len(failed_branch_results),
            "success_count": len(branch_results),
            "failure_count": len(failed_branch_results),
            "partial_success": bool(failed_branch_results),
            "succeeded_branch_ids": sorted(
                str(result.get("branch_id") or "") for result in branch_results
            ),
            "failed_branch_ids": sorted(
                str(result.get("branch_id") or "") for result in failed_branch_results
            ),
        }
    return outputs


def _merge_parallel_outputs(
    merged: dict[str, Any],
    outputs: dict[str, Any],
    *,
    conflict_strategy: str,
    step_id: str,
) -> None:
    for key, value in outputs.items():
        if key not in merged:
            merged[key] = value
            continue
        if conflict_strategy == "error":
            raise StepExecutionError(
                f"parallel_group step {step_id} output conflict for key {key}"
            )
        if conflict_strategy == "first_wins":
            continue
        if conflict_strategy == "last_wins":
            merged[key] = value
            continue
        if conflict_strategy == "last_write":
            merged[key] = value
            continue
        if conflict_strategy == "merge_list":
            existing = merged[key] if isinstance(merged[key], list) else [merged[key]]
            addition = value if isinstance(value, list) else [value]
            merged[key] = [*existing, *addition]
            continue
        if conflict_strategy == "merge_dict":
            if not isinstance(merged[key], dict) or not isinstance(value, dict):
                raise StepExecutionError(
                    f"parallel_group step {step_id} cannot merge non-dict output for {key}"
                )
            merged[key] = {**merged[key], **value}
            continue
        raise StepExecutionError(
            f"unsupported parallel conflict strategy: {conflict_strategy}"
        )


def _enforce_parallel_failure_strategy(
    *,
    failure_strategy: str,
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    min_success: int,
) -> None:
    failure_count = len(failed_branch_results)
    success_count = len(branch_results)
    if failure_strategy in {"fail_fast", "all_success"} and failure_count:
        raise StepExecutionError(f"{failure_count} parallel branch(es) failed")
    if failure_strategy == "min_success" and success_count < max(1, min_success):
        raise StepExecutionError(
            f"parallel_group requires at least {max(1, min_success)} successful branch(es); "
            f"got {success_count}"
        )


def _publish_parallel_branch_artifacts(
    *,
    artifact_manager: ArtifactManager | None,
    run_id: str | None,
    step: StepSpec,
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
) -> list[StorageArtifactRef]:
    if artifact_manager is None or run_id is None:
        return []
    if not _parallel_branch_artifacts_enabled(step):
        return []

    artifact_refs: list[StorageArtifactRef] = []
    for branch_result in [*branch_results, *failed_branch_results]:
        branch_id = str(branch_result.get("branch_id") or "")
        payload = {
            "branch_result": branch_result,
            "outputs": branch_result.get("outputs") or {},
            "metrics": {
                "attempts": branch_result.get("attempts"),
                "duration_ms": branch_result.get("duration_ms"),
                "started_at": branch_result.get("started_at"),
                "finished_at": branch_result.get("finished_at"),
            },
            "error": {
                "error_type": branch_result.get("error_type"),
                "error_message": branch_result.get("error_message"),
            },
        }
        relative_path = f"parallel/{step.step_id}/{branch_id}.json"
        path = artifact_manager.write_json(run_id, relative_path, payload)
        data = path.read_bytes()
        artifact_ref = StorageArtifactRef(
            artifact_id=f"parallel:{step.step_id}:{branch_id}",
            run_id=run_id,
            step_id=step.step_id,
            artifact_type="parallel_branch",
            path=relative_path,
            content_type="application/json",
            size_bytes=len(data),
            checksum=sha256(data).hexdigest(),
            redacted=True,
            metadata={
                "branch_id": branch_id,
                "implementation": branch_result.get("implementation"),
                "status": branch_result.get("status"),
                "manifest_key": f"parallel:{step.step_id}:{branch_id}",
            },
        )
        artifact_payload = artifact_ref.to_dict()
        branch_result.setdefault("artifact_refs", []).append(artifact_payload)
        artifact_refs.append(artifact_ref)
    return artifact_refs


def _parallel_branch_artifacts_enabled(step: StepSpec) -> bool:
    metadata = dict(step.metadata or {})
    if bool(metadata.get("write_branch_artifacts")):
        return True
    policy = step.artifact_policy
    if policy is None:
        return False
    return bool(
        policy.write_step_output or "parallel_branch" in set(policy.artifact_types)
    )


def _parallel_group_lineage(
    step: StepSpec,
    branch_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for branch_result in branch_results:
        branch_id = str(branch_result.get("branch_id") or "")
        output_keys = sorted(str(key) for key in (branch_result.get("outputs") or {}))
        lineage.append(
            {
                "step_id": step.step_id,
                "branch_id": branch_id,
                "output_keys": output_keys,
            }
        )
    return lineage


def _parallel_branch_lineage(
    *,
    step_id: str,
    branch_id: str,
    output_keys: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "step_id": step_id,
            "branch_id": branch_id,
            "output_keys": list(output_keys),
        }
    ]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_metadata_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _elapsed_ms(started: float | None) -> float:
    if started is None:
        return 0.0
    return round((time.perf_counter() - started) * 1000, 3)


def _parallel_group_metrics(
    *,
    branches: list[Any],
    branch_results: list[dict[str, Any]],
    failed_branch_results: list[dict[str, Any]],
    conflict_strategy: str,
    failure_strategy: str,
    min_success: int,
    max_workers: int,
    output_keys: list[str],
) -> dict[str, Any]:
    success_count = len(branch_results)
    failure_count = len(failed_branch_results)
    return {
        "branch_count": len(branches),
        "succeeded_branch_count": success_count,
        "failed_branch_count": failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "partial_success": failure_count > 0,
        "conflict_strategy": conflict_strategy,
        "failure_strategy": failure_strategy,
        "min_success": max(1, min_success),
        "max_workers": min(max_workers, len(branches)),
        "branch_ids": sorted(
            str(result.get("branch_id") or "") for result in branch_results
        ),
        "failed_branch_ids": sorted(
            str(result.get("branch_id") or "") for result in failed_branch_results
        ),
        "output_keys": sorted(output_keys),
        "output_key_count": len(output_keys),
    }


__all__ = ["ParallelGroupStepRunner"]
