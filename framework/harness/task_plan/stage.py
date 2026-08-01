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
from framework.harness.task_plan.scheduler import TaskPlanReadyDecision
from framework.harness.task_plan.store import InMemoryTaskPlanStore, TaskPlanEvent, TaskPlanStorePort, TaskResultRecord
from framework.harness.task_plan.validation import TaskPlanValidationContext, TaskPlanValidator
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.verification import (
    TaskPlanResultVerificationRequest,
    TaskPlanResultVerifier,
)
from framework.harness.workflow.step import HarnessWorkerType


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
        self.patch_validator = TaskPlanPatchValidator()

    def apply_patch(self, request: TaskPlanStageRequest, patch: PlanPatch) -> ValidatedTaskPlan:
        """Validate and durably accept one immutable plan patch version."""
        current = self.store.plan(request.run_id, request.stage_id)
        if current is None:
            raise HarnessValidationError("cannot patch a stage without an accepted plan", code="task_plan_missing_plan")
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
            )
        except HarnessValidationError as exc:
            self.store.append_event(
                TaskPlanEvent(
                    "PLAN_PATCH_REJECTED",
                    run_id=patch.run_id,
                    workflow_id=current.workflow_id,
                    stage_id=patch.stage_id,
                    graph_checksum=current.graph_checksum,
                    plan_id=patch.base_plan_id,
                    plan_version=patch.base_plan_version,
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
            self.store.append_event(TaskPlanEvent(
                "STAGE_OUTPUT_AGGREGATED",
                run_id=request.run_id,
                workflow_id=request.workflow_id,
                stage_id=request.stage_id,
                graph_checksum=request.graph_checksum,
                plan_id=plan.plan_id,
                plan_version=plan.version,
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
            self.store.append_event(TaskPlanEvent(
                "TASK_PLAN_VERIFIED",
                run_id=request.run_id,
                workflow_id=request.workflow_id,
                stage_id=request.stage_id,
                graph_checksum=request.graph_checksum,
                plan_id=plan.plan_id,
                plan_version=plan.version,
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
            self._halt(request, str(exc), exc.code or "task_plan_failure")
            return HarnessWorkerResult(status=HarnessWorkerStatus.BLOCKED, error=str(exc), diagnostics={"reason_code": exc.code})
        except Exception as exc:
            self._halt(request, str(exc), "task_plan_stage_failure")
            return HarnessWorkerResult(status=HarnessWorkerStatus.FAILED, error=str(exc), diagnostics={"reason_code": "task_plan_stage_failure"})

    def _ensure_plan(self, request: TaskPlanStageRequest) -> ValidatedTaskPlan:
        if request.policy_ref is not None and request.policy_ref != request.policy.exact_ref:
            raise HarnessValidationError("TaskPlan request policy ref is not pinned to the supplied policy", code="task_plan_policy_mismatch")
        existing = self.store.plan(request.run_id, request.stage_id)
        if existing is not None:
            if existing.graph_checksum != request.graph_checksum or existing.policy_ref != request.policy.exact_ref:
                raise HarnessValidationError("existing TaskPlan is pinned to incompatible graph or policy", code="task_plan_pinned_version_mismatch")
            return existing
        candidate = request.candidate or self.candidate_builder.build_candidate(PlanBuildRequest(
            run_id=request.run_id,
            workflow_id=request.workflow_id,
            stage_id=request.stage_id,
            graph_checksum=request.graph_checksum,
            context_refs=request.context_refs,
            policy=request.policy,
            budget=request.budget,
            metadata=request.metadata,
        ))
        self.store.append_candidate(candidate)
        context = TaskPlanValidationContext(
            run_id=request.run_id,
            workflow_id=request.workflow_id,
            stage_id=request.stage_id,
            graph_checksum=request.graph_checksum,
            available_input_refs=tuple(request.context_refs.values()),
            registered_gate_refs=request.policy.allowed_gate_refs,
            registered_aggregator_refs=self.aggregator.registry.refs,
            dynamic_stage_declared=True,
        )
        missing_aggregators = sorted({ref for ref in request.policy.deterministic_aggregator_refs.values() if not self.aggregator.registry.contains(ref)})
        if missing_aggregators:
            raise HarnessValidationError("deterministic TaskPlan aggregator is unavailable", code="task_plan_aggregator_unavailable", details={"aggregator_refs": missing_aggregators})
        result = self.validator.validate(candidate, policy=request.policy, capabilities=self.capability_registry, context=context)
        if not result.accepted:
            self.store.append_rejected_candidate(candidate, reason_code=result.diagnostics[0].code if result.diagnostics else "task_plan_candidate_rejected")
            result.require_valid()
        plan = ValidatedTaskPlan(
            plan_id=canonical_payload_checksum({"candidate_checksum": candidate.candidate_checksum, "stage_id": request.stage_id}),
            run_id=candidate.run_id,
            workflow_id=candidate.workflow_id,
            stage_id=candidate.stage_id,
            graph_checksum=request.graph_checksum,
            version=1,
            parent_plan_id=None,
            source_candidate_ref=candidate.candidate_checksum,
            policy_ref=request.policy.exact_ref,
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
            for task_request in decision.task_requests:
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
            for task_request in decision.task_requests:
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
            for task_request in decision.task_requests:
                result = self._invoke(task_request, plan, request.policy)
                self.store.append_result(result)
                if result.status is TaskLifecycle.FAILED:
                    resolved = next(item for item in plan.tasks if item.task_id == result.task_id)
                    if result.attempt < resolved.normalized_retry_policy.max_attempts:
                        current = self.store.load_projection(request.run_id, request.stage_id)
                        retry_tasks = tuple(replace(item, status=TaskLifecycle.PENDING, active_instance_id=None, failure_reason_code=None) if item.task_id == result.task_id else item for item in current.tasks)
                        sequence = self._next_sequence(request)
                        retry_projection = replace(
                            current,
                            tasks=retry_tasks,
                            last_sequence=sequence,
                        )
                        self.store.commit_event(TaskPlanEvent(
                            "TASK_RETRY_SCHEDULED", run_id=request.run_id, workflow_id=request.workflow_id, stage_id=request.stage_id,
                            graph_checksum=request.graph_checksum, plan_id=plan.plan_id, plan_version=plan.version,
                            task_id=result.task_id, task_instance_id=result.task_instance_id, attempt=result.attempt,
                            input_checksum=result.result_checksum, reason_code=result.error_code, sequence=sequence,
                        ), retry_projection)
                    else:
                        raise HarnessValidationError("task retry budget exhausted", code="task_plan_retry_exhausted", details={"task_id": result.task_id})
        raise HarnessValidationError("TaskPlan execution exceeded bounded rounds", code="task_plan_execution_bound_exceeded")

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
            TaskPlanEvent(
                event_type,
                run_id=request.run_id,
                workflow_id=request.workflow_id,
                stage_id=request.stage_id,
                graph_checksum=request.graph_checksum,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                task_id=instance.task_id,
                task_instance_id=instance.task_instance_id,
                attempt=instance.attempt,
                input_checksum=instance.task_definition_checksum,
                sequence=sequence,
            ),
            replace(projection, last_sequence=sequence),
        )

    def _invoke(self, task_request: TaskInstance, plan: ValidatedTaskPlan, policy: Any) -> TaskResultRecord:
        resolved = next(item for item in plan.tasks if item.task_id == task_request.task_id)
        worker_binding = self.capability_registry.resolve(resolved.task.worker_capability, policy)
        worker_result = self._call_binding(worker_binding, task_request)
        if not isinstance(worker_result, HarnessWorkerResult):
            raise HarnessValidationError("dynamic worker returned invalid result", code="task_plan_result_invalid")
        verified = self.result_verifier.verify(
            worker_result,
            task=resolved,
            request=TaskPlanResultVerificationRequest(
                task=resolved,
                instance=task_request,
                worker_result=worker_result,
                workflow_id=plan.workflow_id,
            ),
        )
        return verified

    def _call_binding(self, binding: Any, request: TaskInstance) -> HarnessWorkerResult:
        if self.worker_executor is not None:
            value = self.worker_executor(binding, request)
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

    def _halt(self, request: TaskPlanStageRequest, message: str, reason_code: str) -> None:
        try:
            self.store.append_event(TaskPlanEvent(
                "TASK_PLAN_HALTED", run_id=request.run_id, workflow_id=request.workflow_id, stage_id=request.stage_id,
                graph_checksum=request.graph_checksum,
                reason_code=reason_code,
                payload={
                    "diagnostic_ref": canonical_payload_checksum(
                        {"reason_code": reason_code}
                    )
                },
                sequence=self._next_sequence(request),
            ))
        except Exception:
            return

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


__all__ = ["TaskPlanStageRunner"]
