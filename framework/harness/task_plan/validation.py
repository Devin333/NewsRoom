from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.binding import TaskPlanCapabilityRegistry
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    checksum,
    frozen_mapping,
    exact_reference,
    identifier,
    stable_text_tuple,
    task_reference_producer,
    thaw_mapping,
)
from framework.harness.task_plan.dag import task_dependency_depths
from framework.harness.task_plan.models import (
    PlanCandidate,
    ResolvedTaskSpec,
    TaskBudget,
    TaskPlanLimits,
    TaskSpec,
    ValidatedTaskPlan,
)
from framework.harness.task_plan.policy import TaskPlanPolicy


TASK_PLAN_VALIDATOR_VERSION = "newsroom.harness-task-plan-validator/v1"


@dataclass(frozen=True, slots=True)
class TaskPlanValidationContext:
    run_id: str
    workflow_id: str
    stage_id: str
    graph_checksum: str
    available_input_refs: tuple[str, ...]
    future_stage_input_refs: tuple[str, ...] = ()
    registered_gate_refs: tuple[str, ...] = ()
    registered_aggregator_refs: tuple[str, ...] = ()
    remaining_task_budget: TaskBudget | Mapping[str, Any] | None = None
    dynamic_stage_declared: bool = True

    def __post_init__(self) -> None:
        for name in ("run_id", "workflow_id", "stage_id"):
            object.__setattr__(self, name, identifier(getattr(self, name), name))
        object.__setattr__(self, "graph_checksum", checksum(self.graph_checksum, "graph_checksum"))
        object.__setattr__(self, "available_input_refs", stable_text_tuple(self.available_input_refs, "available_input_refs", item_kind="reference"))
        object.__setattr__(self, "future_stage_input_refs", stable_text_tuple(self.future_stage_input_refs, "future_stage_input_refs", item_kind="reference"))
        object.__setattr__(self, "registered_gate_refs", stable_text_tuple(self.registered_gate_refs, "registered_gate_refs", item_kind="exact_reference"))
        object.__setattr__(self, "registered_aggregator_refs", stable_text_tuple(self.registered_aggregator_refs, "registered_aggregator_refs", item_kind="exact_reference"))
        budget = self.remaining_task_budget
        if budget is not None and not isinstance(budget, TaskBudget):
            if not isinstance(budget, Mapping):
                raise HarnessValidationError("remaining_task_budget must be TaskBudget", code="invalid_task_plan_validation_context")
            budget = TaskBudget.from_dict(budget)
        object.__setattr__(self, "remaining_task_budget", budget)
        if not isinstance(self.dynamic_stage_declared, bool):
            raise HarnessValidationError("dynamic_stage_declared must be a boolean", code="invalid_task_plan_validation_context")


@dataclass(frozen=True, slots=True)
class TaskPlanDiagnostic:
    code: str
    message: str
    phase: str
    task_id: str | None = None
    field: str | None = None
    details: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", identifier(self.code, "diagnostic.code"))
        object.__setattr__(self, "phase", identifier(self.phase, "diagnostic.phase"))
        message = str(self.message).strip()
        if not message or len(message) > 512:
            raise HarnessValidationError("TaskPlan diagnostic message must be bounded", code="invalid_task_plan_diagnostic")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "task_id", str(self.task_id) if self.task_id is not None else None)
        object.__setattr__(self, "field", str(self.field) if self.field is not None else None)
        object.__setattr__(self, "details", frozen_mapping(self.details, "diagnostic.details"))

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (self.phase, self.code, self.task_id or "", self.field or "", canonical_payload_checksum(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "phase": self.phase,
            "task_id": self.task_id,
            "field": self.field,
            "details": thaw_mapping(self.details),
        }


@dataclass(frozen=True, slots=True)
class TaskPlanValidationResult:
    candidate_checksum: str
    policy_ref: str
    accepted: bool
    diagnostics: tuple[TaskPlanDiagnostic, ...]
    resolved_tasks: tuple[ResolvedTaskSpec, ...] = ()
    limits: TaskPlanLimits | None = None
    validator_version: str = TASK_PLAN_VALIDATOR_VERSION
    result_checksum: str = dataclass_field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_checksum", checksum(self.candidate_checksum, "candidate_checksum"))
        object.__setattr__(self, "policy_ref", exact_reference(self.policy_ref, "policy_ref"))
        diagnostics = tuple(sorted(self.diagnostics, key=lambda item: item.sort_key))
        object.__setattr__(self, "diagnostics", diagnostics)
        resolved = tuple(sorted(self.resolved_tasks, key=lambda item: (item.task_id, item.task_definition_checksum)))
        object.__setattr__(self, "resolved_tasks", resolved)
        if self.accepted and (diagnostics or not resolved or self.limits is None):
            raise HarnessValidationError("accepted validation must have resolved tasks and no diagnostics", code="invalid_task_plan_validation_result")
        if not self.accepted and resolved:
            raise HarnessValidationError("rejected validation must not expose partial resolved tasks", code="invalid_task_plan_validation_result")
        object.__setattr__(self, "result_checksum", canonical_payload_checksum(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "validator_version": self.validator_version,
            "candidate_checksum": self.candidate_checksum,
            "policy_ref": self.policy_ref,
            "accepted": self.accepted,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "resolved_tasks": [item.to_dict() for item in self.resolved_tasks],
            "limits": self.limits.to_dict() if self.limits else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "result_checksum": self.result_checksum}

    def require_valid(self) -> tuple[ResolvedTaskSpec, ...]:
        if not self.accepted:
            raise HarnessValidationError(
                "TaskPlan candidate validation failed",
                code="task_plan_candidate_rejected",
                details={"candidate_checksum": self.candidate_checksum, "reason_codes": [item.code for item in self.diagnostics]},
            )
        return self.resolved_tasks


class TaskPlanValidator:
    """Pure, fail-closed candidate validator and plan builder."""

    def validate(
        self,
        candidate: PlanCandidate,
        *,
        policy: TaskPlanPolicy,
        capabilities: TaskPlanCapabilityRegistry,
        context: TaskPlanValidationContext,
    ) -> TaskPlanValidationResult:
        if not isinstance(candidate, PlanCandidate):
            raise TypeError("candidate must be PlanCandidate")
        if not isinstance(policy, TaskPlanPolicy):
            raise TypeError("policy must be TaskPlanPolicy")
        if not callable(getattr(capabilities, "resolve", None)):
            raise TypeError("capabilities must expose resolve(capability, policy)")
        if not isinstance(context, TaskPlanValidationContext):
            raise TypeError("context must be TaskPlanValidationContext")
        diagnostics: list[TaskPlanDiagnostic] = []
        if not context.dynamic_stage_declared:
            diagnostics.append(_diag("stage_not_dynamic", "stage is not declared dynamic", "identity"))
        for name in ("run_id", "workflow_id", "stage_id", "graph_checksum"):
            if getattr(candidate, name) != getattr(context, name):
                diagnostics.append(_diag(f"candidate_{name}_mismatch", f"candidate {name} does not match stage context", "identity", field=name))
        if candidate.stage_id != policy.stage_id:
            diagnostics.append(_diag("candidate_policy_stage_mismatch", "candidate stage does not match policy", "identity", field="stage_id"))
        if len(candidate.tasks) > policy.max_tasks:
            diagnostics.append(_diag("task_count_exceeded", "candidate exceeds max_tasks", "policy", details={"max_tasks": policy.max_tasks}))
        if candidate.requested_max_parallelism > policy.max_parallelism:
            diagnostics.append(_diag("parallelism_exceeded", "candidate requests too much parallelism", "policy"))
        if candidate.requested_plan_budget.exceeds(policy.limits.plan_build_budget):
            diagnostics.append(_diag("plan_build_budget_exceeded", "candidate exceeds plan-builder budget", "policy"))
        if not set(candidate.input_context_refs).issubset(set(policy.allowed_input_refs)):
            diagnostics.append(_diag("candidate_input_not_allowed", "candidate requests context outside policy", "dataflow", details={"refs": sorted(set(candidate.input_context_refs) - set(policy.allowed_input_refs))}))
        candidate_roles = set(candidate.required_output_roles)
        missing = sorted(set(policy.required_output_roles) - candidate_roles)
        extra = sorted(candidate_roles - set(policy.allowed_output_roles))
        if missing or extra:
            diagnostics.append(_diag("required_output_roles_mismatch", "candidate output roles do not match policy", "outputs", details={"missing": missing, "extra": extra}))

        by_id: dict[str, TaskSpec] = {}
        duplicates = [task_id for task_id, count in Counter(task.task_id for task in candidate.tasks).items() if count > 1]
        for task_id in sorted(duplicates):
            diagnostics.append(_diag("duplicate_task_id", "task ids must be unique", "dag", task_id=task_id))
        for task in candidate.tasks:
            by_id.setdefault(task.task_id, task)
        depths = self._validate_dag(by_id, policy.max_depth, diagnostics)
        resolved: dict[str, ResolvedTaskSpec] = {}
        aggregate = {"max_turns": 0, "max_tool_calls": 0, "max_memory_ops": 0, "max_output_tokens": 0}
        for task in candidate.tasks:
            self._validate_task(task, by_id, policy, capabilities, context, diagnostics)
            if task.task_id in resolved:
                continue
            try:
                binding = capabilities.resolve(task.worker_capability, policy)
                resolved[task.task_id] = binding.resolve_task(task, policy)
                for field_name, value in resolved[task.task_id].normalized_budget.to_dict().items():
                    aggregate[field_name] += value
            except HarnessValidationError as exc:
                diagnostics.append(_diag(exc.code or "task_plan_binding_invalid", str(exc), "binding", task_id=task.task_id, details=exc.details or {}))
            except Exception as exc:
                diagnostics.append(_diag("task_plan_binding_invalid", str(exc), "binding", task_id=task.task_id))
        aggregate_limit = policy.aggregate_task_budget
        aggregate_exceeded = [name for name, value in aggregate.items() if value > getattr(aggregate_limit, name)]
        if aggregate_exceeded:
            diagnostics.append(_diag("aggregate_budget_exceeded", "candidate exceeds aggregate task budget", "budget", details={"fields": aggregate_exceeded}))
        if context.remaining_task_budget is not None:
            remaining_exceeded = [name for name, value in aggregate.items() if value > getattr(context.remaining_task_budget, name)]
            if remaining_exceeded:
                diagnostics.append(_diag("remaining_budget_exceeded", "candidate exceeds remaining run budget", "budget", details={"fields": remaining_exceeded}))
        self._validate_outputs(by_id, depths, policy, context, diagnostics)
        diagnostics = _bounded(diagnostics, policy.max_validation_diagnostics)
        accepted = not diagnostics
        return TaskPlanValidationResult(
            candidate_checksum=candidate.candidate_checksum,
            policy_ref=policy.exact_ref,
            accepted=accepted,
            diagnostics=tuple(diagnostics),
            resolved_tasks=tuple(resolved.values()) if accepted else (),
            limits=policy.limits if accepted else None,
        )

    def accept(
        self,
        candidate: PlanCandidate,
        policy: TaskPlanPolicy,
        capabilities: TaskPlanCapabilityRegistry,
        *,
        graph_checksum: str | None = None,
        stage_input_refs: Mapping[str, str] | Sequence[str] = (),
        plan_id: str | None = None,
        accepted_at: str,
        context: TaskPlanValidationContext | None = None,
        aggregator_registered: bool = True,
    ) -> ValidatedTaskPlan:
        if context is None:
            refs = tuple(stage_input_refs.keys()) if isinstance(stage_input_refs, Mapping) else tuple(stage_input_refs)
            context = TaskPlanValidationContext(
                run_id=candidate.run_id,
                workflow_id=candidate.workflow_id,
                stage_id=candidate.stage_id,
                graph_checksum=graph_checksum or candidate.graph_checksum,
                available_input_refs=refs or candidate.input_context_refs,
                registered_gate_refs=policy.allowed_gate_refs,
                dynamic_stage_declared=True,
            )
        result = self.validate(candidate, policy=policy, capabilities=capabilities, context=context)
        if not aggregator_registered:
            raise HarnessValidationError("deterministic aggregator is unavailable", code="task_plan_aggregator_unavailable")
        result.require_valid()
        if plan_id is None:
            plan_id = canonical_payload_checksum({"candidate_checksum": candidate.candidate_checksum, "stage_id": candidate.stage_id})
        return ValidatedTaskPlan(
            plan_id=plan_id,
            run_id=candidate.run_id,
            workflow_id=candidate.workflow_id,
            stage_id=candidate.stage_id,
            graph_checksum=context.graph_checksum,
            version=1,
            parent_plan_id=None,
            source_candidate_ref=candidate.candidate_checksum,
            policy_ref=policy.exact_ref,
            policy_checksum=policy.policy_checksum,
            tasks=result.resolved_tasks,
            required_output_roles=policy.required_output_roles,
            limits=policy.limits,
            accepted_at=accepted_at,
        )

    @staticmethod
    def _validate_dag(by_id: Mapping[str, TaskSpec], max_depth: int, diagnostics: list[TaskPlanDiagnostic]) -> dict[str, int]:
        try:
            return task_dependency_depths(
                {task_id: task.depends_on for task_id, task in by_id.items()},
                max_depth=max_depth,
            )
        except HarnessValidationError as exc:
            diagnostic_code = {
                "task_plan_dependency_cycle": "dependency_cycle",
                "task_plan_no_executable_root": "no_executable_root",
                "task_plan_unreachable_task": "unreachable_task",
            }.get(exc.code or "", exc.code or "task_plan_dag_invalid")
            diagnostics.append(
                _diag(
                    diagnostic_code,
                    str(exc),
                    "dag",
                    task_id=(exc.details or {}).get("task_id"),
                    details=exc.details or {},
                )
            )
            return {}

    @staticmethod
    def _validate_task(task: TaskSpec, by_id: Mapping[str, TaskSpec], policy: TaskPlanPolicy, capabilities: TaskPlanCapabilityRegistry, context: TaskPlanValidationContext, diagnostics: list[TaskPlanDiagnostic]) -> None:
        if task.worker_capability not in policy.allowed_worker_capabilities:
            diagnostics.append(_diag("capability_not_allowed", "task capability is not allowed by policy", "policy", task_id=task.task_id))
        if not set(task.requested_tools).issubset(policy.allowed_tool_ids):
            diagnostics.append(_diag("tool_not_allowed", "task requests a tool outside policy", "policy", task_id=task.task_id))
        if not set(task.requested_memory_namespaces).issubset(policy.allowed_memory_namespaces):
            diagnostics.append(_diag("memory_not_allowed", "task requests memory outside policy", "policy", task_id=task.task_id))
        if task.output_contract.schema_ref not in policy.allowed_output_schema_refs:
            diagnostics.append(_diag("output_schema_not_allowed", "task output schema is outside policy", "outputs", task_id=task.task_id, details={"schema_ref": task.output_contract.schema_ref}))
        unknown_gates = set(task.acceptance_criteria.gate_refs) - set(policy.allowed_gate_refs)
        if unknown_gates:
            diagnostics.append(_diag("gate_not_allowed", "task requests a gate outside policy", "policy", task_id=task.task_id, details={"gates": sorted(unknown_gates)}))
        if context.registered_gate_refs and not set(task.acceptance_criteria.gate_refs).issubset(context.registered_gate_refs):
            diagnostics.append(_diag("gate_unregistered", "task references an unregistered gate", "binding", task_id=task.task_id))
        for ref in task.input_refs:
            if ref in context.future_stage_input_refs:
                diagnostics.append(_diag("future_stage_reference", "task references a future stage input", "dataflow", task_id=task.task_id, details={"ref": ref}))
                continue
            producer = task_reference_producer(ref, tuple(by_id))
            if producer is not None:
                if producer not in by_id:
                    diagnostics.append(_diag("task_plan_unknown_dependency", "task input references an unknown producer", "dataflow", task_id=task.task_id, details={"ref": ref, "producer_task_id": producer}))
                    continue
                if producer not in task.depends_on:
                    diagnostics.append(_diag("task_plan_task_input_dependency_missing", "task input reference must be declared as a dependency", "dataflow", task_id=task.task_id, details={"ref": ref, "producer_task_id": producer}))
            elif ref not in policy.allowed_input_refs or ref not in context.available_input_refs:
                diagnostics.append(_diag("task_plan_input_reference_unavailable", "task input reference is not authorized and available in this stage", "dataflow", task_id=task.task_id, details={"ref": ref}))
        for ref in task.output_contract.metadata.values():
            if isinstance(ref, str) and ref in {"route", "quality_passed", "publish_artifact", "write_memory", "halt_workflow"}:
                diagnostics.append(_diag("forbidden_control_field", "task output metadata contains a control field", "forbidden", task_id=task.task_id))

    @staticmethod
    def _validate_outputs(by_id: Mapping[str, TaskSpec], depths: Mapping[str, int], policy: TaskPlanPolicy, context: TaskPlanValidationContext, diagnostics: list[TaskPlanDiagnostic]) -> None:
        producers: dict[str, list[str]] = {}
        for task in by_id.values():
            producers.setdefault(task.output_contract.output_role, []).append(task.task_id)
        for role in policy.required_output_roles:
            if role not in producers:
                diagnostics.append(_diag("missing_required_output_role", "required output role has no producer", "outputs", details={"role": role}))
        for role, task_ids in producers.items():
            if role not in policy.allowed_output_roles:
                diagnostics.append(_diag("output_role_not_allowed", "task output role is not allowed", "outputs", details={"role": role}))
            if len(task_ids) > 1 and role not in policy.deterministic_aggregator_refs:
                diagnostics.append(_diag("output_role_conflict", "multiple tasks produce one role without an aggregator", "outputs", details={"role": role, "task_ids": sorted(task_ids)}))
            if len(task_ids) > 1 and policy.deterministic_aggregator_refs.get(role) not in context.registered_aggregator_refs:
                diagnostics.append(_diag("aggregator_unregistered", "declared deterministic aggregator is unavailable", "outputs", details={"role": role}))
        required_producers = {task_id for role in policy.required_output_roles for task_id in producers.get(role, ())}
        if required_producers:
            reverse: dict[str, set[str]] = {task_id: set() for task_id in by_id}
            for task in by_id.values():
                for dependency in task.depends_on:
                    reverse.setdefault(dependency, set()).add(task.task_id)
            reachable: set[str] = set()
            queue = deque(task_id for task_id, task in by_id.items() if not task.depends_on)
            while queue:
                task_id = queue.popleft()
                if task_id in reachable:
                    continue
                reachable.add(task_id)
                queue.extend(sorted(reverse.get(task_id, ())))
            for task_id in sorted(set(by_id) - reachable):
                diagnostics.append(_diag("unreachable_task", "task is not reachable from a stage root", "dag", task_id=task_id))
            for task_id in sorted(required_producers - reachable):
                diagnostics.append(_diag("unreachable_required_output", "required output producer is unreachable from a root", "dag", task_id=task_id))


def _diag(code: str, message: str, phase: str, *, task_id: str | None = None, field: str | None = None, details: Mapping[str, Any] | None = None) -> TaskPlanDiagnostic:
    return TaskPlanDiagnostic(code=code, message=message, phase=phase, task_id=task_id, field=field, details=details or {})


def _bounded(diagnostics: list[TaskPlanDiagnostic], limit: int) -> list[TaskPlanDiagnostic]:
    ordered: list[TaskPlanDiagnostic] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for diagnostic in sorted(diagnostics, key=lambda item: item.sort_key):
        key = (diagnostic.code, diagnostic.task_id, diagnostic.field)
        if key not in seen:
            ordered.append(diagnostic)
            seen.add(key)
    if len(ordered) > limit:
        ordered = ordered[:limit]
    return ordered


__all__ = ["TASK_PLAN_VALIDATOR_VERSION", "TaskPlanDiagnostic", "TaskPlanValidationContext", "TaskPlanValidationResult", "TaskPlanValidator"]
