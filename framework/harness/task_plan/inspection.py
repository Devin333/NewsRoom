"""Authorized, reference-only TaskPlan inspection projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    checksum,
    identifier,
    optional_text,
    reference,
)
from framework.harness.task_plan.models import TaskPlanProjection, ValidatedTaskPlan
from framework.harness.task_plan.store import TaskPlanEvent, TaskPlanStorePort
from framework.harness.workflow.canonical import freeze_json, thaw_json


_DEFAULT_MAX_TASKS = 128
_DEFAULT_MAX_EVENTS = 512


@dataclass(frozen=True, slots=True)
class TaskPlanInspectionRequest:
    run_id: str
    stage_id: str
    principal_id: str
    tenant_id: str | None
    authentication_evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", identifier(self.run_id, "run_id"))
        object.__setattr__(self, "stage_id", identifier(self.stage_id, "stage_id"))
        object.__setattr__(
            self,
            "principal_id",
            identifier(self.principal_id, "principal_id"),
        )
        tenant_id = optional_text(self.tenant_id, "tenant_id")
        object.__setattr__(
            self,
            "tenant_id",
            None if tenant_id is None else identifier(tenant_id, "tenant_id"),
        )
        object.__setattr__(
            self,
            "authentication_evidence_ref",
            reference(
                self.authentication_evidence_ref,
                "authentication_evidence_ref",
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskPlanInspectionDecision:
    authorized: bool
    authorization_evidence_ref: str | None = None
    denial_reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be a bool")
        evidence_ref = self.authorization_evidence_ref
        if evidence_ref is not None:
            evidence_ref = reference(evidence_ref, "authorization_evidence_ref")
        reason_code = optional_text(self.denial_reason_code, "denial_reason_code")
        if self.authorized and evidence_ref is None:
            raise HarnessValidationError(
                "authorized TaskPlan inspection requires authorization evidence",
                code="task_plan_inspection_authorization_missing",
            )
        if not self.authorized and reason_code is None:
            raise HarnessValidationError(
                "denied TaskPlan inspection requires a stable reason code",
                code="task_plan_inspection_denial_missing",
            )
        object.__setattr__(self, "authorization_evidence_ref", evidence_ref)
        object.__setattr__(self, "denial_reason_code", reason_code)


@runtime_checkable
class TaskPlanInspectionAuthorizer(Protocol):
    def authorize(
        self,
        request: TaskPlanInspectionRequest,
    ) -> TaskPlanInspectionDecision: ...


@dataclass(frozen=True, slots=True)
class TaskPlanReplayVerdict:
    passed: bool
    decision_checksum: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        decision_checksum = self.decision_checksum
        if decision_checksum is not None:
            decision_checksum = checksum(decision_checksum, "decision_checksum")
        reason_code = optional_text(self.reason_code, "reason_code")
        if not self.passed and reason_code is None:
            raise HarnessValidationError(
                "failed replay verdict requires a reason code",
                code="task_plan_replay_verdict_invalid",
            )
        object.__setattr__(self, "decision_checksum", decision_checksum)
        object.__setattr__(self, "reason_code", reason_code)


@dataclass(frozen=True, slots=True)
class TaskPlanInspection:
    projection: Mapping[str, Any]

    def __post_init__(self) -> None:
        projection = freeze_json(self.projection, "task_plan_inspection")
        if not isinstance(projection, Mapping):
            raise TypeError("projection must be a mapping")
        object.__setattr__(self, "projection", projection)

    def to_dict(self) -> dict[str, Any]:
        return thaw_json(self.projection)


class TaskPlanInspectionService:
    """Authorizes before reading the TaskPlan store and projects safe fields only."""

    def __init__(
        self,
        *,
        store: TaskPlanStorePort,
        authorizer: TaskPlanInspectionAuthorizer,
        max_tasks: int = _DEFAULT_MAX_TASKS,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> None:
        if not isinstance(store, TaskPlanStorePort):
            raise TypeError("store must implement TaskPlanStorePort")
        if not isinstance(authorizer, TaskPlanInspectionAuthorizer):
            raise TypeError("authorizer must implement TaskPlanInspectionAuthorizer")
        self._store = store
        self._authorizer = authorizer
        self._max_tasks = _positive_limit(max_tasks, "max_tasks")
        self._max_events = _positive_limit(max_events, "max_events")

    def inspect(
        self,
        request: TaskPlanInspectionRequest,
        *,
        replay: TaskPlanReplayVerdict | None = None,
    ) -> TaskPlanInspection:
        if not isinstance(request, TaskPlanInspectionRequest):
            raise TypeError("request must be TaskPlanInspectionRequest")
        if replay is not None and not isinstance(replay, TaskPlanReplayVerdict):
            raise TypeError("replay must be TaskPlanReplayVerdict")
        decision = self._authorizer.authorize(request)
        if not isinstance(decision, TaskPlanInspectionDecision):
            raise HarnessValidationError(
                "TaskPlan inspection authorizer returned an invalid decision",
                code="task_plan_inspection_authorization_invalid",
            )
        if not decision.authorized:
            raise HarnessValidationError(
                "TaskPlan inspection is not authorized",
                code="task_plan_inspection_unauthorized",
                details={"reason_code": decision.denial_reason_code},
            )

        projection = self._store.load_projection(request.run_id, request.stage_id)
        plan = self._store.plan(request.run_id, request.stage_id)
        if plan is None:
            raise HarnessValidationError(
                "TaskPlan inspection has no accepted plan",
                code="task_plan_inspection_plan_missing",
            )
        _require_matching_projection(projection, plan)
        events = self._store.read_events(request.run_id, request.stage_id)
        history = _plan_history(self._store, plan)
        return TaskPlanInspection(
            _inspection_projection(
                request=request,
                authorization=decision,
                plan=plan,
                history=history,
                projection=projection,
                events=events,
                replay=replay,
                max_tasks=self._max_tasks,
                max_events=self._max_events,
            )
        )


def _inspection_projection(
    *,
    request: TaskPlanInspectionRequest,
    authorization: TaskPlanInspectionDecision,
    plan: ValidatedTaskPlan,
    history: tuple[ValidatedTaskPlan, ...],
    projection: TaskPlanProjection,
    events: tuple[TaskPlanEvent, ...],
    replay: TaskPlanReplayVerdict | None,
    max_tasks: int,
    max_events: int,
) -> dict[str, Any]:
    plans_by_version = {
        item.version: {
            "plan_id": item.plan_id,
            "plan_version": item.version,
            "plan_checksum": item.plan_checksum,
            "parent_plan_id": item.parent_plan_id,
            "source_candidate_ref": item.source_candidate_ref,
            "policy_ref": item.policy_ref,
        }
        for item in history
    }
    task_definitions = {item.task_id: item for item in plan.tasks}
    task_states = tuple(projection.tasks[:max_tasks])
    tasks = []
    for state in task_states:
        definition = task_definitions.get(state.task_id)
        if definition is None:
            raise HarnessValidationError(
                "TaskPlan projection references an absent task definition",
                code="task_plan_inspection_projection_mismatch",
            )
        tasks.append(
            {
                "task_id": state.task_id,
                "status": state.status.value,
                "depends_on": list(definition.depends_on),
                "attempts": state.attempts,
                "active_instance_id": state.active_instance_id,
                "worker_ref": definition.worker_ref,
                "worker_capability": definition.task.worker_capability,
                "output_role": definition.output_role,
                "output_schema_ref": definition.task.output_contract.schema_ref,
                "result_ref": None if state.result is None else state.result.result_ref,
                "result_checksum": (
                    None if state.result is None else state.result.result_checksum
                ),
                "failure_reason_code": state.failure_reason_code,
            }
        )
    event_window = events[-max_events:]
    candidate_refs, patch_refs = _event_refs(event_window)
    state_counts = Counter(item.status.value for item in projection.tasks)
    return {
        "schema_version": "newsroom.harness-task-plan-inspection/v1",
        "run_id": request.run_id,
        "stage_id": request.stage_id,
        "authorization_evidence_ref": authorization.authorization_evidence_ref,
        "graph_checksum": projection.graph_checksum,
        "policy_ref": projection.policy_ref,
        "current_plan": plans_by_version[plan.version],
        "plan_history": [plans_by_version[key] for key in sorted(plans_by_version)],
        "candidate_refs": candidate_refs,
        "patch_refs": patch_refs,
        "task_counts": dict(sorted(state_counts.items())),
        "tasks": tasks,
        "tasks_truncated": len(projection.tasks) > len(tasks),
        "budget": _bounded_budget(projection.consumed_budget),
        "replans": max(plan.version - 1, 0),
        "retries": sum(max(item.attempts - 1, 0) for item in projection.tasks),
        "last_durable_sequence": projection.last_sequence,
        "events_visible": len(event_window),
        "events_truncated": len(events) > len(event_window),
        "replay": None
        if replay is None
        else {
            "passed": replay.passed,
            "decision_checksum": replay.decision_checksum,
            "reason_code": replay.reason_code,
        },
    }


def _event_refs(events: tuple[TaskPlanEvent, ...]) -> tuple[list[str], list[str]]:
    candidate_refs: set[str] = set()
    patch_refs: set[str] = set()
    for event in events:
        candidate = event.payload.get("candidate_ref")
        if isinstance(candidate, str):
            candidate_refs.add(candidate)
        patch = event.payload.get("patch_ref")
        if isinstance(patch, str):
            patch_refs.add(patch)
    return sorted(candidate_refs), sorted(patch_refs)


def _plan_history(
    store: TaskPlanStorePort,
    current: ValidatedTaskPlan,
) -> tuple[ValidatedTaskPlan, ...]:
    history: list[ValidatedTaskPlan] = []
    for version in range(1, current.version + 1):
        plan = store.plan(current.run_id, current.stage_id, version)
        if plan is None:
            raise HarnessValidationError(
                "TaskPlan inspection history is incomplete",
                code="task_plan_inspection_history_missing",
                details={"plan_version": version},
            )
        history.append(plan)
    return tuple(history)


def _bounded_budget(value: Mapping[str, Any]) -> dict[str, int]:
    items: list[tuple[str, int]] = []
    for key, item in sorted(value.items()):
        if len(items) >= 32:
            break
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        items.append((str(key), item))
    return dict(items)


def _require_matching_projection(
    projection: TaskPlanProjection,
    plan: ValidatedTaskPlan,
) -> None:
    fields = ("run_id", "stage_id", "graph_checksum", "plan_id", "plan_checksum")
    if any(getattr(projection, name) != getattr(plan, name) for name in fields):
        raise HarnessValidationError(
            "TaskPlan inspection projection identity does not match its plan",
            code="task_plan_inspection_projection_mismatch",
        )
    if projection.plan_version != plan.version or projection.policy_ref != plan.policy_ref:
        raise HarnessValidationError(
            "TaskPlan inspection projection version does not match its plan",
            code="task_plan_inspection_projection_mismatch",
        )


def _positive_limit(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="task_plan_inspection_limit_invalid",
        )
    return value


__all__ = [
    "TaskPlanInspection",
    "TaskPlanInspectionAuthorizer",
    "TaskPlanInspectionDecision",
    "TaskPlanInspectionRequest",
    "TaskPlanInspectionService",
    "TaskPlanReplayVerdict",
]
