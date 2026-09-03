from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.scheduler import HarnessScheduler
from framework.harness.task_plan.aggregator import TaskPlanAggregator
from framework.harness.task_plan.binding import TaskPlanCapabilityRegistry
from framework.harness.task_plan.models import TaskLifecycle, ValidatedTaskPlan, TaskInstance
from framework.harness.task_plan.ports import (
    PlanBuildRequest,
    PlanCandidateBuilderPort,
    TaskPlanResultVerifierPort,
    TaskPlanStageRequest,
    TaskPlanStageRunnerPort,
)
from framework.harness.task_plan.patches import TaskPlanPatchValidator
from framework.harness.task_plan.models import PlanPatch
from framework.harness.task_plan.scheduler import (
    TaskPlanReadyDecision,
    task_instance_for_attempt,
)
from framework.harness.task_plan.store import (
    TaskPlanEvent,
    TaskPlanStorePort,
    TaskResultRecord,
    _task_plan_event_identity_kwargs,
)
from framework.harness.task_plan.validation import TaskPlanValidationContext, TaskPlanValidator
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.verification import (
    TaskPlanResultVerificationRequest,
    TaskPlanResultVerifier,
)
from framework.harness.graph.activity import HarnessWorkerType


class TaskPlanStageRunner(TaskPlanStageRunnerPort):
    """Harness-owned PLAN -> EXECUTE -> VERIFY runner for a dynamic stage."""

    def __init__(
        self,
        *,
        candidate_builder: PlanCandidateBuilderPort,
        capability_registry: TaskPlanCapabilityRegistry,
        store: TaskPlanStorePort,
        validator: TaskPlanValidator | None = None,
        scheduler: HarnessScheduler | None = None,
        aggregator: TaskPlanAggregator | None = None,
        result_verifier: TaskPlanResultVerifierPort | None = None,
        worker_executor: Any | None = None,
        worker_result_recovery: Any | None = None,
    ) -> None:
        if not isinstance(store, TaskPlanStorePort):
            raise TypeError("store must implement TaskPlanStorePort")
        if result_verifier is not None and not isinstance(
            result_verifier, TaskPlanResultVerifierPort
        ):
            raise TypeError("result_verifier must implement TaskPlanResultVerifierPort")
        self.candidate_builder = candidate_builder
        self.capability_registry = capability_registry
        self.store = store
        self.validator = validator or TaskPlanValidator()
        if scheduler is not None and not isinstance(scheduler, HarnessScheduler):
            raise TypeError("scheduler must be HarnessScheduler")
        self.scheduler = scheduler or HarnessScheduler()
        self.aggregator = aggregator or TaskPlanAggregator()
        self.result_verifier = result_verifier or TaskPlanResultVerifier()
        self.worker_executor = worker_executor
        if worker_result_recovery is not None and not callable(worker_result_recovery):
            raise TypeError("worker_result_recovery must be callable")
        self.worker_result_recovery = worker_result_recovery
        self.patch_validator = TaskPlanPatchValidator()

    def apply_patch(self, request: TaskPlanStageRequest, patch: PlanPatch) -> ValidatedTaskPlan:
        """Validate and durably accept one immutable plan patch version."""
        current = self.store.plan(request.run_id, request.stage_id)
        if current is None:
            raise HarnessValidationError("cannot patch a stage without an accepted plan", code="task_plan_missing_plan")
        _require_plan_stage_binding(current, request)
        self.patch_validator.require_policy_identity(current, request.policy)
        projection = self.store.load_projection(request.run_id, request.stage_id)
        self.store.append_patch(patch, accepted=False)
        try:
            next_plan = self.patch_validator.apply(
                current,
                patch,
                projection,
                request.policy,
                self.capability_registry,
                accepted_at=_required_observation_time(request),
                available_input_refs=tuple(request.context_refs.values()),
            )
        except HarnessValidationError as exc:
            self.store.append_event(
                TaskPlanEvent.for_plan(
                    "PLAN_PATCH_REJECTED",
                    current,
                    input_checksum=patch.patch_checksum,
                    reason_code=exc.code or "task_plan_patch_rejected",
                    payload={"patch_ref": patch.patch_checksum},
                    sequence=self._next_sequence(request),
                )
            )
            raise
        skip_ids = {
            operation.target_task_id
            for operation in patch.operations
            if operation.operation.value == "SKIP_PENDING_TASK"
            and operation.target_task_id is not None
        }
        self.store.accept_patched_plan(
            patch,
            next_plan,
            skipped_task_ids=tuple(sorted(skip_ids)),
        )
        return next_plan

    def run(self, request: TaskPlanStageRequest) -> HarnessWorkerResult:
        try:
            plan = self._ensure_plan(request)
            self._execute_plan(request, plan)
            projection = self.store.load_projection(request.run_id, request.stage_id)
            results = self.store.results_for(request.run_id, request.stage_id, plan.plan_id, plan.version)
            aggregate = self.aggregator.aggregate(results, request.policy)
            self.store.append_event(TaskPlanEvent.for_plan(
                "STAGE_OUTPUT_AGGREGATED",
                plan,
                input_checksum=aggregate.aggregate_checksum,
                output_refs=tuple(aggregate.output_refs_by_role.values()),
                payload={
                    "aggregate_ref": aggregate.aggregate_ref,
                    "aggregate_checksum": aggregate.aggregate_checksum,
                    "output_refs_by_role": dict(aggregate.output_refs_by_role),
                    "result_refs": list(aggregate.result_refs),
                    "branch_refs": [dict(item) for item in aggregate.branch_refs],
                },
                sequence=self._next_sequence(request),
            ))
            self.store.append_event(TaskPlanEvent.for_plan(
                "TASK_PLAN_VERIFIED",
                plan,
                input_checksum=aggregate.aggregate_checksum,
                output_refs=tuple(aggregate.output_refs_by_role.values()),
                sequence=self._next_sequence(request),
            ))
            return HarnessWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={
                    "aggregate_ref": aggregate.aggregate_ref,
                    "aggregate_checksum": aggregate.aggregate_checksum,
                    "output_refs_by_role": dict(aggregate.output_refs_by_role),
                    "analysis_branch_refs": [dict(item) for item in aggregate.branch_refs],
                },
                diagnostics={"plan_id": plan.plan_id, "plan_version": plan.version, "projection_checksum": projection.projection_checksum},
            )
        except HarnessValidationError as exc:
            self._halt(request, exc.code or "task_plan_failure")
            return HarnessWorkerResult(status=HarnessWorkerStatus.BLOCKED, error=str(exc), diagnostics={"reason_code": exc.code})
        except Exception as exc:
            self._halt(request, "task_plan_stage_failure")
            return HarnessWorkerResult(status=HarnessWorkerStatus.FAILED, error=str(exc), diagnostics={"reason_code": "task_plan_stage_failure"})

    def _ensure_plan(self, request: TaskPlanStageRequest) -> ValidatedTaskPlan:
        if request.policy_ref is not None and request.policy_ref != request.policy.exact_ref:
            raise HarnessValidationError("TaskPlan request policy ref is not pinned to the supplied policy", code="task_plan_policy_mismatch")
        existing = self.store.plan(request.run_id, request.stage_id)
        if existing is not None:
            _require_plan_stage_binding(existing, request)
            self.patch_validator.require_policy_identity(existing, request.policy)
            return existing
        candidate = request.candidate or self.candidate_builder.build_candidate(PlanBuildRequest(
            run_id=request.run_id,
            stage_binding=request.stage_binding,
            context_refs=request.context_refs,
            policy=request.policy,
            budget=request.budget,
            metadata=request.metadata,
            execution_identity=request.execution_identity,
        ))
        self.store.append_candidate(candidate)
        context = TaskPlanValidationContext(
            run_id=request.run_id,
            stage_binding=request.stage_binding,
            available_input_refs=tuple(request.context_refs.values()),
            registered_gate_refs=_registered_gate_refs(
                self.result_verifier,
                fallback=request.policy.allowed_gate_refs,
            ),
            registered_aggregator_refs=self.aggregator.registry.refs,
        )
        missing_aggregators = sorted({ref for ref in request.policy.deterministic_aggregator_refs.values() if not self.aggregator.registry.contains(ref)})
        if missing_aggregators:
            raise HarnessValidationError("deterministic TaskPlan aggregator is unavailable", code="task_plan_aggregator_unavailable", details={"aggregator_refs": missing_aggregators})
        result = self.validator.validate(candidate, policy=request.policy, capabilities=self.capability_registry, context=context)
        if not result.accepted:
            self.store.append_rejected_candidate(candidate, reason_code=result.diagnostics[0].code if result.diagnostics else "task_plan_candidate_rejected")
            result.require_valid()
        plan = ValidatedTaskPlan.from_candidate(
            candidate,
            plan_id=canonical_payload_checksum({"candidate_checksum": candidate.candidate_checksum, "stage_id": request.stage_id}),
            version=1,
            parent_plan_id=None,
            source_candidate_ref=candidate.candidate_checksum,
            policy_ref=request.policy.exact_ref,
            policy_checksum=request.policy.policy_checksum,
            tasks=result.resolved_tasks,
            required_output_roles=request.policy.required_output_roles,
            limits=request.policy.limits,
            accepted_at=_required_observation_time(request),
        )
        self.store.accept_plan(plan)
        return plan

    def _execute_plan(self, request: TaskPlanStageRequest, plan: ValidatedTaskPlan) -> None:
        max_rounds = max(1, plan.limits.max_tasks * plan.limits.max_task_attempts + plan.limits.max_replans + 1)
        for _ in range(max_rounds):
            projection = self.store.load_projection(request.run_id, request.stage_id)
            if self._recover_committed_subagent_results(request, plan, projection):
                continue
            if self._recover_failed_task_retries(request, plan, projection):
                continue
            decision = self.scheduler.next_task_plan_decision(
                projection,
                plan.limits.max_parallelism,
                plan=plan,
                policy=request.policy,
                available_input_refs=tuple(request.context_refs.values()),
            )
            if not decision.task_requests:
                pending = [item.task_id for item in projection.tasks if item.status in {TaskLifecycle.PENDING, TaskLifecycle.READY, TaskLifecycle.DISPATCHED, TaskLifecycle.RUNNING}]
                failed = [item.task_id for item in projection.tasks if item.status is TaskLifecycle.FAILED]
                if pending or failed:
                    raise HarnessValidationError("TaskPlan cannot make further progress", code="task_plan_task_blocked", details={"pending": pending, "failed": failed, "blocked": list(decision.blocked_task_ids)})
                return
            for task_request in decision.task_requests:
                current = self.store.load_projection(request.run_id, request.stage_id)
                reserved = self.scheduler.reserve_task_plan_tasks(
                    current,
                    TaskPlanReadyDecision((task_request,)),
                )
                self._commit_task_transition(
                    request,
                    plan,
                    task_request,
                    "TASK_READY",
                    reserved,
                )
                projection = self.scheduler.mark_task_plan_dispatched(
                    self.store.load_projection(request.run_id, request.stage_id),
                    task_request,
                )
                self._commit_task_transition(
                    request,
                    plan,
                    task_request,
                    "TASK_DISPATCHED",
                    projection,
                )
                projection = self.scheduler.mark_task_plan_started(
                    self.store.load_projection(request.run_id, request.stage_id),
                    task_request,
                )
                self._commit_task_transition(
                    request,
                    plan,
                    task_request,
                    "TASK_STARTED",
                    projection,
                )
                result = self._invoke(
                    task_request,
                    plan,
                    request.policy,
                    execution_identity=request.execution_identity,
                )
                self.store.append_result(result)
                if result.status is TaskLifecycle.FAILED:
                    resolved = next(item for item in plan.tasks if item.task_id == result.task_id)
                    retryable_codes = set(resolved.normalized_retry_policy.retryable_reason_codes)
                    if (
                        result.error_code in retryable_codes
                        and result.attempt < resolved.normalized_retry_policy.max_attempts
                    ):
                        current = self.store.load_projection(request.run_id, request.stage_id)
                        retry_tasks = tuple(replace(item, status=TaskLifecycle.PENDING, active_instance_id=None, failure_reason_code=None) if item.task_id == result.task_id else item for item in current.tasks)
                        sequence = self._next_sequence(request)
                        retry_projection = replace(
                            current,
                            tasks=retry_tasks,
                            last_sequence=sequence,
                        )
                        self.store.commit_event(TaskPlanEvent.for_plan(
                            "TASK_RETRY_SCHEDULED", plan,
                            task_id=result.task_id, task_instance_id=result.task_instance_id, attempt=result.attempt,
                            input_checksum=result.result_checksum, reason_code=result.error_code, sequence=sequence,
                        ), retry_projection)
                    elif result.error_code not in retryable_codes:
                        raise HarnessValidationError(
                            "task failure is outside the task retry policy",
                            code="task_plan_retry_not_allowed",
                            details={
                                "task_id": result.task_id,
                                "attempt": result.attempt,
                                "error_code": result.error_code,
                                "retryable_reason_codes": sorted(retryable_codes),
                            },
                        )
                    else:
                        raise HarnessValidationError("task retry budget exhausted", code="task_plan_retry_exhausted", details={"task_id": result.task_id})
        raise HarnessValidationError("TaskPlan execution exceeded bounded rounds", code="task_plan_execution_bound_exceeded")

    def _recover_failed_task_retries(
        self,
        request: TaskPlanStageRequest,
        plan: ValidatedTaskPlan,
        projection: Any,
    ) -> bool:
        """Complete a retry decision interrupted after result persistence.

        ``append_result`` durably records a failed attempt before the retry
        decision event is appended.  A process restart in that small window
        must re-use the same policy decision instead of treating the failed
        projection as an opaque blocker or invoking the worker directly.
        """

        definitions = {item.task_id: item for item in plan.tasks}
        for state in projection.tasks:
            if state.status is not TaskLifecycle.FAILED:
                continue
            definition = definitions[state.task_id]
            retryable_codes = set(
                definition.normalized_retry_policy.retryable_reason_codes
            )
            reason_code = state.failure_reason_code
            if reason_code not in retryable_codes:
                raise HarnessValidationError(
                    "task failure is outside the task retry policy",
                    code="task_plan_retry_not_allowed",
                    details={
                        "task_id": state.task_id,
                        "attempt": state.attempts,
                        "error_code": reason_code,
                        "retryable_reason_codes": sorted(retryable_codes),
                    },
                )
            if state.attempts >= definition.normalized_retry_policy.max_attempts:
                raise HarnessValidationError(
                    "task retry budget exhausted",
                    code="task_plan_retry_exhausted",
                    details={
                        "task_id": state.task_id,
                        "attempt": state.attempts,
                    },
                )
            result_checksum = _failed_result_checksum(
                self.store.read_events(request.run_id, request.stage_id),
                task_id=state.task_id,
                task_instance_id=state.active_instance_id,
                attempt=state.attempts,
            )
            if result_checksum is None:
                raise HarnessValidationError(
                    "failed TaskPlan retry is missing durable result evidence",
                    code="task_plan_retry_evidence_missing",
                    details={"task_id": state.task_id, "attempt": state.attempts},
                )
            current = self.store.load_projection(request.run_id, request.stage_id)
            retry_tasks = tuple(
                replace(
                    item,
                    status=TaskLifecycle.PENDING,
                    active_instance_id=None,
                    failure_reason_code=None,
                )
                if item.task_id == state.task_id
                else item
                for item in current.tasks
            )
            sequence = self._next_sequence(request)
            self.store.commit_event(
                TaskPlanEvent.for_plan(
                    "TASK_RETRY_SCHEDULED",
                    plan,
                    task_id=state.task_id,
                    task_instance_id=state.active_instance_id,
                    attempt=state.attempts,
                    input_checksum=result_checksum,
                    reason_code=reason_code,
                    sequence=sequence,
                ),
                replace(
                    current,
                    tasks=retry_tasks,
                    last_sequence=sequence,
                ),
            )
            return True
        return False

    def _recover_committed_subagent_results(
        self,
        request: TaskPlanStageRequest,
        plan: ValidatedTaskPlan,
        projection: Any,
    ) -> bool:
        if self.worker_result_recovery is None:
            return False
        recovered_any = False
        definitions = {item.task_id: item for item in plan.tasks}
        for state in projection.tasks:
            definition = definitions[state.task_id]
            if definition.subagent_id is None or state.status not in {
                TaskLifecycle.DISPATCHED,
                TaskLifecycle.RUNNING,
            }:
                continue
            if state.active_instance_id is None or state.attempts <= 0:
                raise HarnessValidationError(
                    "active subagent task is missing attempt identity",
                    code="task_plan_recovery_attempt_missing",
                )
            instance = task_instance_for_attempt(
                plan,
                state.task_id,
                state.attempts,
                task_instance_id=state.active_instance_id,
            )
            binding = self.capability_registry.resolve(
                definition.task.worker_capability,
                request.policy,
            )
            candidate = (
                self.worker_result_recovery(binding, instance)
                if request.execution_identity is None
                else self.worker_result_recovery(
                    binding,
                    instance,
                    request.execution_identity,
                )
            )
            if candidate is None:
                raise HarnessValidationError(
                    "active subagent attempt has no committed outcome receipt",
                    code="task_plan_subagent_attempt_indeterminate",
                    details={"task_id": state.task_id, "attempt": state.attempts},
                )
            if not isinstance(candidate, HarnessWorkerResult):
                raise HarnessValidationError(
                    "subagent result recovery returned invalid evidence",
                    code="task_plan_result_invalid",
                )
            verified = self.result_verifier.verify(
                candidate,
                task=definition,
                request=TaskPlanResultVerificationRequest(
                    plan=plan,
                    task=definition,
                    instance=instance,
                    worker_result=candidate,
                    execution_identity=request.execution_identity,
                ),
            )
            self.store.append_result(verified)
            recovered_any = True
        return recovered_any

    def _commit_task_transition(
        self,
        request: TaskPlanStageRequest,
        plan: ValidatedTaskPlan,
        instance: TaskInstance,
        event_type: str,
        projection: Any,
    ) -> None:
        sequence = self._next_sequence(request)
        self.store.commit_event(
            TaskPlanEvent.for_plan(
                event_type,
                plan,
                task_id=instance.task_id,
                task_instance_id=instance.task_instance_id,
                attempt=instance.attempt,
                input_checksum=instance.task_definition_checksum,
                sequence=sequence,
            ),
            replace(projection, last_sequence=sequence),
        )

    def _invoke(
        self,
        task_request: TaskInstance,
        plan: ValidatedTaskPlan,
        policy: Any,
        *,
        execution_identity: Any | None,
    ) -> TaskResultRecord:
        resolved = next(item for item in plan.tasks if item.task_id == task_request.task_id)
        worker_binding = self.capability_registry.resolve(resolved.task.worker_capability, policy)
        worker_result = self._call_binding(
            worker_binding,
            task_request,
            execution_identity=execution_identity,
        )
        if not isinstance(worker_result, HarnessWorkerResult):
            raise HarnessValidationError("dynamic worker returned invalid result", code="task_plan_result_invalid")
        verified = self.result_verifier.verify(
            worker_result,
            task=resolved,
            request=TaskPlanResultVerificationRequest(
                plan=plan,
                task=resolved,
                instance=task_request,
                worker_result=worker_result,
                execution_identity=execution_identity,
            ),
        )
        return verified

    def _call_binding(
        self,
        binding: Any,
        request: TaskInstance,
        *,
        execution_identity: Any | None,
    ) -> HarnessWorkerResult:
        if self.worker_executor is not None:
            value = (
                self.worker_executor(binding, request)
                if execution_identity is None
                else self.worker_executor(binding, request, execution_identity)
            )
        else:
            if (
                binding.registration.worker_binding.worker_type
                is HarnessWorkerType.SUBAGENT
            ):
                raise HarnessValidationError(
                    "dynamic subagent tasks require the resolved SubAgent runtime adapter",
                    code="task_plan_subagent_runtime_required",
                )
            implementation = binding.registration.worker_binding.implementation
            execute = getattr(implementation, "execute", None)
            if not callable(execute):
                raise HarnessValidationError("dynamic worker binding has no runtime executor", code="task_plan_binding_unavailable")
            value = execute({
                "task": request.to_dict(),
                "allowed_tools": list(binding.allowed_tools),
                "allowed_memory_namespaces": list(binding.allowed_memory_namespaces),
            })
        if isinstance(value, HarnessWorkerResult):
            return value
        if isinstance(value, dict):
            return HarnessWorkerResult(**value)
        raise HarnessValidationError("dynamic worker returned invalid result", code="task_plan_result_invalid")

    def _halt(self, request: TaskPlanStageRequest, reason_code: str) -> None:
        try:
            plan = self.store.plan(request.run_id, request.stage_id)
            diagnostic_ref = canonical_payload_checksum({"reason_code": reason_code})
            event = (
                TaskPlanEvent.for_plan(
                    "TASK_PLAN_HALTED",
                    plan,
                    reason_code=reason_code,
                    payload={"diagnostic_ref": diagnostic_ref},
                    sequence=self._next_sequence(request),
                )
                if plan is not None
                else TaskPlanEvent(
                    "TASK_PLAN_HALTED",
                    **_task_plan_event_identity_kwargs(request.stage_identity),
                    reason_code=reason_code,
                    payload={"diagnostic_ref": diagnostic_ref},
                    sequence=self._next_sequence(request),
                )
            )
            self.store.append_event(event)
        except Exception as exc:
            raise HarnessValidationError(
                "TaskPlan halt could not be durably committed",
                code="task_plan_halt_persistence_failed",
                details={
                    "run_id": request.run_id,
                    "stage_id": request.stage_id,
                    "plan_version": plan.version if "plan" in locals() and plan is not None else None,
                    "reason_code": reason_code,
                    "diagnostic_ref": canonical_payload_checksum({"reason_code": reason_code}),
                },
            ) from exc

    def _next_sequence(self, request: TaskPlanStageRequest) -> int:
        return len(self.store.read_events(request.run_id, request.stage_id)) + 1


def _required_observation_time(request: TaskPlanStageRequest) -> str:
    value = request.accepted_at
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(
            "TaskPlan stage requires an explicit accepted_at observation",
            code="task_plan_observation_time_required",
        )
    return value


def _registered_gate_refs(
    verifier: TaskPlanResultVerifierPort,
    *,
    fallback: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return only gate refs exposed by the concrete verifier registry.

    ``fallback`` remains a source-compatible argument for older callers, but
    policy allowlists are never treated as executable gate registration.
    """

    del fallback
    refs = getattr(verifier, "registered_gate_refs", None)
    if refs is None:
        return ()
    return tuple(refs)


def _failed_result_checksum(
    events: tuple[TaskPlanEvent, ...],
    *,
    task_id: str,
    task_instance_id: str | None,
    attempt: int,
) -> str | None:
    for event in reversed(events):
        if (
            event.event_type != "TASK_RESULT_REJECTED"
            or event.task_id != task_id
            or event.task_instance_id != task_instance_id
            or event.attempt != attempt
        ):
            continue
        value = event.payload.get("result_checksum")
        return value if isinstance(value, str) else None
    return None


def _require_plan_stage_binding(
    plan: ValidatedTaskPlan,
    request: TaskPlanStageRequest,
) -> None:
    if (
        not plan.matches_stage_identity(request.stage_identity)
        or plan.policy_ref != request.stage_binding.policy_ref
    ):
        raise HarnessValidationError(
            "existing TaskPlan is outside the frozen Graph stage binding",
            code="task_plan_pinned_version_mismatch",
            details={
                "expected_stage_binding_ref": request.stage_binding.binding_checksum,
                "expected_stage_identity": request.stage_identity.to_dict(),
                "actual_plan_identity": plan.to_dict(),
            },
        )


__all__ = ["TaskPlanStageRunner"]
