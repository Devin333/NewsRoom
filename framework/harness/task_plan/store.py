from __future__ import annotations

from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Any, Mapping, Protocol, runtime_checkable

from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    checksum,
    exact_keys,
    exact_reference,
    frozen_mapping,
    identifier,
    non_negative_int,
    optional_text,
    positive_int,
    reference,
    required_text,
    stable_text_tuple,
    thaw_mapping,
)
from framework.harness.task_plan.models import (
    PlanCandidate,
    PlanPatch,
    TaskLifecycle,
    TaskPlanProjection,
    TaskProjection,
    TaskResultReference,
    ValidatedTaskPlan,
)
from framework.harness.task_plan.schema import (
    GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    TASK_PLAN_EVENT_SCHEMA_V1,
    TASK_PLAN_EVENT_SCHEMA_V2,
    TASK_PLAN_EVENT_SCHEMAS,
)


# Compatibility alias: the legacy runtime remains the default writer until
# production Graph authority is explicitly enabled.
TASK_PLAN_EVENT_SCHEMA = TASK_PLAN_EVENT_SCHEMA_V1
TASK_PLAN_RESULT_SCHEMA_V1 = "newsroom.harness-task-plan-result/v1"
TASK_PLAN_RESULT_SCHEMA_V2 = "newsroom.harness-task-plan-result/v2"
TASK_PLAN_EVENT_TYPES = (
    "PLAN_CANDIDATE_BUILT",
    "PLAN_CANDIDATE_REJECTED",
    "PLAN_VALIDATION_FAILED",
    "PLAN_ACCEPTED",
    "TASK_READY",
    "TASK_DISPATCHED",
    "TASK_STARTED",
    "TASK_RETRY_SCHEDULED",
    "TASK_RESULT_ACCEPTED",
    "TASK_RESULT_REJECTED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_BLOCKED",
    "TASK_SKIPPED",
    "PLAN_PATCH_PROPOSED",
    "PLAN_PATCH_REJECTED",
    "PLAN_PATCH_ACCEPTED",
    "STAGE_OUTPUT_AGGREGATED",
    "TASK_PLAN_VERIFIED",
    "TASK_PLAN_HALTED",
)


@dataclass(frozen=True, slots=True)
class TaskResultRecord:
    """Durable task result envelope; payload itself remains outside the plan."""

    run_id: str
    workflow_id: str
    stage_id: str
    plan_id: str
    plan_version: int
    task_id: str
    task_instance_id: str
    attempt: int
    worker_ref: str
    task_checksum: str
    binding_checksum: str
    status: TaskLifecycle | str
    result_ref: str | None = None
    output_refs: tuple[str, ...] = ()
    output_roles: tuple[str, ...] = ()
    output_schema_ref: str = "schema://task-result@1"
    usage: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    verified_gate_refs: tuple[str, ...] = ()
    gate_evidence_refs: tuple[str, ...] = ()
    transcript_ref: str | None = None
    transcript_checksum: str | None = None
    subagent_output_ref: str | None = None
    subagent_output_checksum: str | None = None
    schema_version: str = TASK_PLAN_RESULT_SCHEMA_V2
    result_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version not in {
            TASK_PLAN_RESULT_SCHEMA_V1,
            TASK_PLAN_RESULT_SCHEMA_V2,
        }:
            raise HarnessValidationError(
                "TaskResultRecord schema is unsupported",
                code="task_plan_result_schema_unsupported",
            )
        for name in ("run_id", "workflow_id", "stage_id", "plan_id", "task_id", "task_instance_id"):
            object.__setattr__(self, name, identifier(getattr(self, name), name))
        object.__setattr__(self, "plan_version", positive_int(self.plan_version, "plan_version"))
        object.__setattr__(self, "attempt", positive_int(self.attempt, "attempt"))
        object.__setattr__(self, "worker_ref", exact_reference(self.worker_ref, "worker_ref"))
        object.__setattr__(self, "task_checksum", checksum(self.task_checksum, "task_checksum"))
        object.__setattr__(self, "binding_checksum", checksum(self.binding_checksum, "binding_checksum"))
        try:
            status = TaskLifecycle(self.status)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "task result status must be succeeded or failed",
                code="task_plan_result_invalid",
            ) from exc
        if status not in {TaskLifecycle.SUCCEEDED, TaskLifecycle.FAILED}:
            raise HarnessValidationError(
                "task result status must be succeeded or failed",
                code="task_plan_result_invalid",
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "result_ref", reference(self.result_ref, "result_ref") if self.result_ref else None)
        object.__setattr__(self, "output_refs", stable_text_tuple(self.output_refs, "output_refs", item_kind="reference"))
        object.__setattr__(self, "output_roles", stable_text_tuple(self.output_roles, "output_roles"))
        object.__setattr__(self, "output_schema_ref", exact_reference(self.output_schema_ref, "output_schema_ref"))
        object.__setattr__(self, "usage", frozen_mapping(self.usage, "result.usage"))
        object.__setattr__(self, "error_code", optional_text(self.error_code, "error_code"))
        object.__setattr__(
            self,
            "verified_gate_refs",
            stable_text_tuple(
                self.verified_gate_refs,
                "verified_gate_refs",
                item_kind="exact_reference",
            ),
        )
        object.__setattr__(
            self,
            "gate_evidence_refs",
            stable_text_tuple(
                self.gate_evidence_refs,
                "gate_evidence_refs",
                item_kind="reference",
            ),
        )
        evidence_values = (
            self.transcript_ref,
            self.transcript_checksum,
            self.subagent_output_ref,
            self.subagent_output_checksum,
        )
        if self.schema_version == TASK_PLAN_RESULT_SCHEMA_V1 and any(
            item is not None for item in evidence_values
        ):
            raise HarnessValidationError(
                "legacy TaskResultRecord must not carry v2 evidence",
                code="task_plan_result_invalid",
            )
        if any(item is not None for item in evidence_values) and not all(
            item is not None for item in evidence_values
        ):
            raise HarnessValidationError(
                "TaskPlan subagent evidence fields must be complete",
                code="task_plan_result_invalid",
            )
        object.__setattr__(
            self,
            "transcript_ref",
            reference(self.transcript_ref, "transcript_ref")
            if self.transcript_ref
            else None,
        )
        object.__setattr__(
            self,
            "transcript_checksum",
            checksum(self.transcript_checksum, "transcript_checksum")
            if self.transcript_checksum
            else None,
        )
        object.__setattr__(
            self,
            "subagent_output_ref",
            reference(self.subagent_output_ref, "subagent_output_ref")
            if self.subagent_output_ref
            else None,
        )
        object.__setattr__(
            self,
            "subagent_output_checksum",
            checksum(self.subagent_output_checksum, "subagent_output_checksum")
            if self.subagent_output_checksum
            else None,
        )
        if self.gate_evidence_refs and len(self.gate_evidence_refs) != len(
            self.verified_gate_refs
        ):
            raise HarnessValidationError(
                "TaskPlan gate evidence must correspond one-to-one with verified gates",
                code="task_plan_result_invalid",
            )
        if self.status is TaskLifecycle.SUCCEEDED and not self.result_ref:
            raise HarnessValidationError("successful task result requires result_ref", code="task_plan_result_invalid")
        if self.status is TaskLifecycle.SUCCEEDED:
            if not self.output_roles:
                raise HarnessValidationError(
                    "successful task result requires output_roles",
                    code="task_plan_result_invalid",
                )
            if self.error_code is not None:
                raise HarnessValidationError(
                    "successful task result must not carry error_code",
                    code="task_plan_result_invalid",
                )
        elif self.error_code is None:
            raise HarnessValidationError(
                "failed task result requires error_code",
                code="task_plan_result_invalid",
            )
        elif self.result_ref is not None or self.output_roles or self.output_refs:
            raise HarnessValidationError(
                "failed task result must not carry accepted output references",
                code="task_plan_result_invalid",
            )
        if (
            self.status is TaskLifecycle.SUCCEEDED
            and self.subagent_output_ref is not None
            and self.result_ref != self.subagent_output_ref
        ):
            raise HarnessValidationError(
                "successful subagent result_ref must use its durable output ref",
                code="task_plan_result_invalid",
            )
        object.__setattr__(self, "result_checksum", canonical_payload_checksum(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "stage_id": self.stage_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "task_id": self.task_id,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
            "worker_ref": self.worker_ref,
            "task_checksum": self.task_checksum,
            "binding_checksum": self.binding_checksum,
            "status": self.status.value,
            "result_ref": self.result_ref,
            "output_refs": list(self.output_refs),
            "output_roles": list(self.output_roles),
            "output_schema_ref": self.output_schema_ref,
            "usage": thaw_mapping(self.usage),
            "error_code": self.error_code,
            "verified_gate_refs": list(self.verified_gate_refs),
            "gate_evidence_refs": list(self.gate_evidence_refs),
        }
        if self.schema_version == TASK_PLAN_RESULT_SCHEMA_V2:
            payload = {
                "schema_version": self.schema_version,
                **payload,
                "transcript_ref": self.transcript_ref,
                "transcript_checksum": self.transcript_checksum,
                "subagent_output_ref": self.subagent_output_ref,
                "subagent_output_checksum": self.subagent_output_checksum,
            }
        return payload

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        payload = self.checksum_projection()
        if include_checksum:
            payload["result_checksum"] = self.result_checksum
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskResultRecord":
        common = frozenset(
            {
                "run_id", "workflow_id", "stage_id", "plan_id", "plan_version",
                "task_id", "task_instance_id", "attempt", "worker_ref",
                "task_checksum", "binding_checksum", "status", "result_ref",
                "output_refs", "output_roles", "output_schema_ref", "usage",
                "error_code", "verified_gate_refs", "gate_evidence_refs",
                "result_checksum",
            }
        )
        if "schema_version" not in value:
            payload = exact_keys(value, required=common, model=cls.__name__)
            payload["schema_version"] = TASK_PLAN_RESULT_SCHEMA_V1
        else:
            payload = exact_keys(
                value,
                required=common
                | {
                    "schema_version", "transcript_ref", "transcript_checksum",
                    "subagent_output_ref", "subagent_output_checksum",
                },
                model=cls.__name__,
            )
        supplied = checksum(payload.pop("result_checksum"), "result_checksum")
        result = cls(**payload)
        if supplied != result.result_checksum:
            raise HarnessValidationError("TaskResultRecord checksum does not match canonical content", code="task_plan_checksum_mismatch")
        return result


_GRAPH_ONLY_TASK_PLAN_EVENT_IDENTITY_FIELDS = frozenset(
    {
        "graph_id",
        "graph_version",
        "graph_ref",
        "graph_schema_version",
        "compiler_version",
        "condition_policy_version",
        "stage_binding_checksum",
        "stage_identity_schema",
        "stage_identity_checksum",
    }
)


def _normalize_task_plan_event_identity(event: Any) -> None:
    if event.schema_version == TASK_PLAN_EVENT_SCHEMA_V1:
        object.__setattr__(
            event,
            "workflow_id",
            identifier(event.workflow_id, "workflow_id"),
        )
        unexpected = sorted(
            name
            for name in _GRAPH_ONLY_TASK_PLAN_EVENT_IDENTITY_FIELDS
            if getattr(event, name) is not None
        )
        if unexpected:
            raise HarnessValidationError(
                "legacy TaskPlan event cannot carry Graph-only identity",
                code="task_plan_event_identity_schema_mismatch",
                details={"unexpected": unexpected},
            )
        return

    if event.workflow_id is not None:
        raise HarnessValidationError(
            "Graph-only TaskPlan event cannot carry legacy orchestration identity",
            code="legacy_task_plan_identity_forbidden",
        )
    normalized = {
        "graph_id": identifier(event.graph_id, "graph_id"),
        "graph_version": identifier(event.graph_version, "graph_version"),
        "graph_ref": exact_reference(event.graph_ref, "graph_ref"),
        "graph_schema_version": required_text(
            event.graph_schema_version,
            "graph_schema_version",
        ),
        "compiler_version": required_text(
            event.compiler_version,
            "compiler_version",
        ),
        "condition_policy_version": required_text(
            event.condition_policy_version,
            "condition_policy_version",
        ),
        "stage_binding_checksum": checksum(
            event.stage_binding_checksum,
            "stage_binding_checksum",
        ),
        "stage_identity_schema": required_text(
            event.stage_identity_schema,
            "stage_identity_schema",
        ),
        "stage_identity_checksum": checksum(
            event.stage_identity_checksum,
            "stage_identity_checksum",
        ),
    }
    expected = {
        "graph_schema_version": GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "stage_identity_schema": GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
        "graph_ref": f"{normalized['graph_id']}@{normalized['graph_version']}",
    }
    mismatched = {
        name: {"expected": expected_value, "actual": normalized[name]}
        for name, expected_value in expected.items()
        if normalized[name] != expected_value
    }
    if mismatched:
        raise HarnessValidationError(
            "Graph-only TaskPlan event identity versions do not match",
            code="task_plan_graph_identity_mismatch",
            details={"mismatched": mismatched},
        )
    for name, value in normalized.items():
        object.__setattr__(event, name, value)
    identity_projection = {
        "schema_version": event.stage_identity_schema,
        "run_id": event.run_id,
        "graph_schema_version": event.graph_schema_version,
        "compiler_version": event.compiler_version,
        "condition_policy_version": event.condition_policy_version,
        "graph_id": event.graph_id,
        "graph_version": event.graph_version,
        "graph_checksum": event.graph_checksum,
        "stage_id": event.stage_id,
        "stage_binding_checksum": event.stage_binding_checksum,
        "graph_ref": event.graph_ref,
    }
    expected_identity_checksum = canonical_payload_checksum(identity_projection)
    if event.stage_identity_checksum != expected_identity_checksum:
        raise HarnessValidationError(
            "Graph-only TaskPlan event stage identity checksum does not match",
            code="task_plan_stage_identity_checksum_invalid",
            details={
                "expected": expected_identity_checksum,
                "actual": event.stage_identity_checksum,
            },
        )


@dataclass(frozen=True, slots=True)
class TaskPlanEvent:
    event_type: str
    run_id: str
    workflow_id: str | None
    stage_id: str
    graph_checksum: str
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_schema_version: str | None = None
    compiler_version: str | None = None
    condition_policy_version: str | None = None
    stage_binding_checksum: str | None = None
    stage_identity_schema: str | None = None
    stage_identity_checksum: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    task_id: str | None = None
    task_instance_id: str | None = None
    attempt: int | None = None
    schema_version: str = TASK_PLAN_EVENT_SCHEMA
    actor_type: str = "harness"
    causal_event_ref: str | None = None
    input_checksum: str | None = None
    output_refs: tuple[str, ...] = ()
    reason_code: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    event_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if self.event_type not in TASK_PLAN_EVENT_TYPES:
            raise HarnessValidationError("unknown TaskPlan event type", code="task_plan_unknown_event")
        if self.schema_version not in TASK_PLAN_EVENT_SCHEMAS:
            raise HarnessValidationError(
                "unsupported TaskPlan event schema",
                code="unsupported_task_plan_event_schema",
                details={"schema_version": str(self.schema_version)},
            )
        for name in ("run_id", "stage_id"):
            object.__setattr__(self, name, identifier(getattr(self, name), name))
        object.__setattr__(self, "graph_checksum", checksum(self.graph_checksum, "graph_checksum"))
        _normalize_task_plan_event_identity(self)
        object.__setattr__(self, "plan_id", identifier(self.plan_id, "plan_id") if self.plan_id else None)
        if self.plan_version is not None:
            object.__setattr__(self, "plan_version", positive_int(self.plan_version, "plan_version"))
        object.__setattr__(self, "task_id", identifier(self.task_id, "task_id") if self.task_id else None)
        object.__setattr__(self, "task_instance_id", identifier(self.task_instance_id, "task_instance_id") if self.task_instance_id else None)
        if self.attempt is not None:
            object.__setattr__(self, "attempt", positive_int(self.attempt, "attempt"))
        object.__setattr__(self, "actor_type", required_text(self.actor_type, "actor_type"))
        object.__setattr__(self, "causal_event_ref", reference(self.causal_event_ref, "causal_event_ref") if self.causal_event_ref else None)
        object.__setattr__(self, "input_checksum", checksum(self.input_checksum, "input_checksum") if self.input_checksum else None)
        object.__setattr__(self, "output_refs", stable_text_tuple(self.output_refs, "output_refs", item_kind="reference"))
        object.__setattr__(self, "reason_code", optional_text(self.reason_code, "reason_code"))
        object.__setattr__(self, "payload", frozen_mapping(self.payload, "event.payload"))
        sequence = non_negative_int(self.sequence, "sequence")
        if sequence == 0:
            raise HarnessValidationError(
                "TaskPlan event sequence must be positive",
                code="task_plan_invalid_event_sequence",
            )
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "event_checksum", canonical_payload_checksum(self.to_dict(include_checksum=False)))

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_type": self.event_type,
            "run_id": self.run_id,
        }
        if self.is_graph_only:
            payload.update(
                {
                    "graph_id": self.graph_id,
                    "graph_version": self.graph_version,
                    "graph_ref": self.graph_ref,
                    "graph_schema_version": self.graph_schema_version,
                    "compiler_version": self.compiler_version,
                    "condition_policy_version": self.condition_policy_version,
                }
            )
        else:
            payload["workflow_id"] = self.workflow_id
        payload.update(
            {
                "stage_id": self.stage_id,
                "graph_checksum": self.graph_checksum,
                **(
                    {
                        "stage_binding_checksum": self.stage_binding_checksum,
                        "stage_identity_schema": self.stage_identity_schema,
                        "stage_identity_checksum": self.stage_identity_checksum,
                    }
                    if self.is_graph_only
                    else {}
                ),
                "plan_id": self.plan_id,
                "plan_version": self.plan_version,
                "task_id": self.task_id,
                "task_instance_id": self.task_instance_id,
                "attempt": self.attempt,
                "schema_version": self.schema_version,
                "actor_type": self.actor_type,
                "causal_event_ref": self.causal_event_ref,
                "input_checksum": self.input_checksum,
                "output_refs": list(self.output_refs),
                "reason_code": self.reason_code,
                "payload": thaw_mapping(self.payload),
                "sequence": self.sequence,
            }
        )
        if include_checksum:
            payload["event_checksum"] = self.event_checksum
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskPlanEvent":
        schema_version = value.get("schema_version")
        if schema_version not in TASK_PLAN_EVENT_SCHEMAS:
            raise HarnessValidationError(
                "unsupported TaskPlan event schema",
                code="unsupported_task_plan_event_schema",
                details={"schema_version": str(schema_version)},
            )
        common = frozenset(
            {
                "event_type",
                "run_id",
                "stage_id",
                "graph_checksum",
                "plan_id",
                "plan_version",
                "task_id",
                "task_instance_id",
                "attempt",
                "schema_version",
                "actor_type",
                "causal_event_ref",
                "input_checksum",
                "output_refs",
                "reason_code",
                "payload",
                "sequence",
                "event_checksum",
            }
        )
        identity = (
            _GRAPH_ONLY_TASK_PLAN_EVENT_IDENTITY_FIELDS
            if schema_version == TASK_PLAN_EVENT_SCHEMA_V2
            else frozenset({"workflow_id"})
        )
        payload = exact_keys(
            value,
            required=common | identity,
            model=cls.__name__,
        )
        supplied = checksum(payload.pop("event_checksum"), "event_checksum")
        if schema_version == TASK_PLAN_EVENT_SCHEMA_V2:
            payload["workflow_id"] = None
        event = cls(**payload)
        if supplied != event.event_checksum:
            raise HarnessValidationError("TaskPlanEvent checksum does not match canonical content", code="task_plan_checksum_mismatch")
        return event

    @property
    def is_graph_only(self) -> bool:
        return self.schema_version == TASK_PLAN_EVENT_SCHEMA_V2

    def matches_contract_identity(
        self,
        value: PlanCandidate | ValidatedTaskPlan,
    ) -> bool:
        if not isinstance(value, (PlanCandidate, ValidatedTaskPlan)):
            raise TypeError("value must be PlanCandidate or ValidatedTaskPlan")
        if self.is_graph_only != value.is_graph_only:
            return False
        if (
            self.run_id,
            self.stage_id,
            self.graph_checksum,
        ) != (
            value.run_id,
            value.stage_id,
            value.graph_checksum,
        ):
            return False
        if not self.is_graph_only:
            return self.workflow_id == value.workflow_id
        return all(
            getattr(self, name) == getattr(value, name)
            for name in _GRAPH_ONLY_TASK_PLAN_EVENT_IDENTITY_FIELDS
        )


@runtime_checkable
class TaskPlanStorePort(Protocol):
    def append_candidate(self, candidate: PlanCandidate, *, event_type: str = "PLAN_CANDIDATE_BUILT") -> str: ...
    def append_rejected_candidate(self, candidate: PlanCandidate, *, reason_code: str) -> str: ...
    def accept_plan(self, plan: ValidatedTaskPlan) -> str: ...
    def append_patch(self, patch: PlanPatch, *, accepted: bool = False) -> str: ...
    def accept_patched_plan(
        self,
        patch: PlanPatch,
        plan: ValidatedTaskPlan,
        *,
        skipped_task_ids: tuple[str, ...] = (),
    ) -> str: ...
    def append_result(self, result: TaskResultRecord) -> str: ...
    def load_projection(self, run_id: str, stage_id: str) -> TaskPlanProjection: ...
    def read_events(self, run_id: str, stage_id: str) -> tuple[TaskPlanEvent, ...]: ...
    def update_projection(self, projection: TaskPlanProjection) -> None: ...
    def results_for(self, run_id: str, stage_id: str, plan_id: str, plan_version: int) -> tuple[TaskResultRecord, ...]: ...
    def append_event(self, event: TaskPlanEvent) -> str: ...
    def commit_event(self, event: TaskPlanEvent, projection: TaskPlanProjection) -> str: ...
    def plan(self, run_id: str, stage_id: str, version: int | None = None) -> ValidatedTaskPlan | None: ...


class InMemoryTaskPlanStore:
    """Deterministic test store with immutable plan history and projections."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._candidates: dict[str, PlanCandidate] = {}
        self._plans: dict[tuple[str, str, int], ValidatedTaskPlan] = {}
        self._patches: dict[str, PlanPatch] = {}
        self._results: dict[tuple[str, str, str, int, int], TaskResultRecord] = {}
        self._projections: dict[tuple[str, str], TaskPlanProjection] = {}
        self._events: dict[tuple[str, str], list[TaskPlanEvent]] = {}

    def append_candidate(self, candidate: PlanCandidate, *, event_type: str = "PLAN_CANDIDATE_BUILT") -> str:
        if not isinstance(candidate, PlanCandidate):
            raise TypeError("candidate must be PlanCandidate")
        with self._lock:
            existing = self._candidates.get(candidate.candidate_checksum)
            if existing is not None and existing != candidate:
                raise HarnessValidationError("candidate checksum identity conflict", code="task_plan_checksum_conflict")
            if existing is not None:
                return existing.candidate_checksum
            self._candidates[candidate.candidate_checksum] = candidate
            self._append_event(_candidate_event(candidate, event_type, self._next_sequence(candidate.run_id, candidate.stage_id)))
        return candidate.candidate_checksum

    def append_rejected_candidate(self, candidate: PlanCandidate, *, reason_code: str) -> str:
        if not isinstance(candidate, PlanCandidate):
            raise TypeError("candidate must be PlanCandidate")
        with self._lock:
            existing = self._candidates.get(candidate.candidate_checksum)
            if existing is not None and existing != candidate:
                raise HarnessValidationError(
                    "candidate checksum identity conflict",
                    code="task_plan_checksum_conflict",
                )
            self._candidates.setdefault(candidate.candidate_checksum, candidate)
            sequence = self._next_sequence(candidate.run_id, candidate.stage_id)
            rejected = _candidate_event(
                candidate,
                "PLAN_CANDIDATE_REJECTED",
                sequence,
                reason_code=reason_code,
            )
            validation_failed = _candidate_event(
                candidate,
                "PLAN_VALIDATION_FAILED",
                sequence + 1,
                reason_code=reason_code,
            )
            self._append_event(rejected)
            self._append_event(validation_failed)
            projection = self._projections.get((candidate.run_id, candidate.stage_id))
            if projection is not None:
                self._projections[(candidate.run_id, candidate.stage_id)] = replace(
                    projection,
                    last_sequence=sequence + 1,
                )
            return candidate.candidate_checksum

    def accept_plan(self, plan: ValidatedTaskPlan) -> str:
        if not isinstance(plan, ValidatedTaskPlan):
            raise TypeError("plan must be ValidatedTaskPlan")
        key = (plan.run_id, plan.stage_id, plan.version)
        with self._lock:
            current = self._current_plan(plan.run_id, plan.stage_id)
            if current is not None:
                if plan.version != current.version + 1 or plan.parent_plan_id != current.plan_id:
                    raise HarnessValidationError("TaskPlan version is not monotonic", code="task_plan_version_conflict")
            elif plan.version != 1:
                raise HarnessValidationError("initial TaskPlan version must be 1", code="task_plan_version_conflict")
            if (
                plan.source_candidate_ref not in self._candidates
                and plan.source_candidate_ref not in self._patches
                and not any(plan.source_candidate_ref == item.candidate_checksum for item in self._candidates.values())
            ):
                raise HarnessValidationError("accepted plan candidate ref is missing", code="task_plan_candidate_missing")
            existing = self._plans.get(key)
            if existing is not None:
                if existing.plan_checksum != plan.plan_checksum:
                    raise HarnessValidationError("plan version checksum conflict", code="task_plan_checksum_conflict")
                return existing.plan_checksum
            self._plans[key] = plan
            sequence = self._next_sequence(plan.run_id, plan.stage_id)
            previous_projection = self._projections.get((plan.run_id, plan.stage_id))
            self._projections[(plan.run_id, plan.stage_id)] = _projection_for_plan(plan, sequence=sequence, previous=previous_projection)
            self._append_event(_plan_event(plan, "PLAN_ACCEPTED", sequence))
            return plan.plan_checksum

    def append_patch(self, patch: PlanPatch, *, accepted: bool = False) -> str:
        if not isinstance(patch, PlanPatch):
            raise TypeError("patch must be PlanPatch")
        with self._lock:
            existing = self._patches.get(patch.patch_checksum)
            if existing is not None and existing != patch:
                raise HarnessValidationError("patch checksum identity conflict", code="task_plan_checksum_conflict")
            self._patches[patch.patch_checksum] = patch
            plan = self._current_plan(patch.run_id, patch.stage_id)
            if plan is None:
                raise HarnessValidationError(
                    "cannot append a patch without an accepted base plan",
                    code="task_plan_projection_missing",
                )
            graph_checksum = plan.graph_checksum
            workflow_id = plan.workflow_id
            event_type = "PLAN_PATCH_ACCEPTED" if accepted else "PLAN_PATCH_PROPOSED"
            sequence = self._next_sequence(patch.run_id, patch.stage_id)
            event = TaskPlanEvent(event_type, run_id=patch.run_id, workflow_id=workflow_id, stage_id=patch.stage_id, graph_checksum=graph_checksum, plan_id=patch.base_plan_id, plan_version=patch.base_plan_version, input_checksum=patch.patch_checksum, reason_code=patch.reason_code, payload={"patch_ref": patch.patch_checksum}, sequence=sequence)
            self._append_event(event)
            projection = self._projections.get((patch.run_id, patch.stage_id))
            if projection is not None:
                self._projections[(patch.run_id, patch.stage_id)] = replace(
                    projection,
                    last_sequence=sequence,
                )
            return patch.patch_checksum

    def accept_patched_plan(
        self,
        patch: PlanPatch,
        plan: ValidatedTaskPlan,
        *,
        skipped_task_ids: tuple[str, ...] = (),
    ) -> str:
        """Atomically commit an accepted patch, its new plan, and skips."""

        if not isinstance(patch, PlanPatch) or not isinstance(plan, ValidatedTaskPlan):
            raise TypeError("patch and plan must use TaskPlan contracts")
        skip_ids = tuple(sorted(set(identifier(item, "skipped_task_ids") for item in skipped_task_ids)))
        with self._lock:
            current = self._current_plan(patch.run_id, patch.stage_id)
            if current is None or current.plan_id != patch.base_plan_id or current.version != patch.base_plan_version:
                raise HarnessValidationError(
                    "patched plan base is stale",
                    code="task_plan_stale_patch",
                )
            if plan.parent_plan_id != current.plan_id or plan.version != current.version + 1:
                raise HarnessValidationError(
                    "patched plan version is not monotonic",
                    code="task_plan_version_conflict",
                )
            if plan.source_candidate_ref != patch.patch_checksum:
                raise HarnessValidationError(
                    "patched plan source does not match patch checksum",
                    code="task_plan_patch_checksum_mismatch",
                )
            existing = self._plans.get((plan.run_id, plan.stage_id, plan.version))
            if existing is not None:
                if existing.plan_checksum != plan.plan_checksum:
                    raise HarnessValidationError(
                        "patched plan version checksum conflict",
                        code="task_plan_checksum_conflict",
                    )
                return existing.plan_checksum
            self._patches.setdefault(patch.patch_checksum, patch)
            graph_checksum = current.graph_checksum
            sequence = self._next_sequence(plan.run_id, plan.stage_id)
            patch_event = TaskPlanEvent(
                "PLAN_PATCH_ACCEPTED",
                run_id=patch.run_id,
                workflow_id=current.workflow_id,
                stage_id=patch.stage_id,
                graph_checksum=graph_checksum,
                plan_id=patch.base_plan_id,
                plan_version=patch.base_plan_version,
                input_checksum=patch.patch_checksum,
                reason_code=patch.reason_code,
                payload={"patch_ref": patch.patch_checksum},
                sequence=sequence,
            )
            plan_event = _plan_event(plan, "PLAN_ACCEPTED", sequence + 1)
            previous_projection = self._projections.get((plan.run_id, plan.stage_id))
            next_projection = _projection_for_plan(
                plan,
                sequence=plan_event.sequence,
                previous=previous_projection,
            )
            events = [patch_event, plan_event]
            for task_id in skip_ids:
                state = next((item for item in next_projection.tasks if item.task_id == task_id), None)
                if state is None:
                    raise HarnessValidationError(
                        "patched plan skip references unknown task",
                        code="task_plan_unknown_task",
                        details={"task_id": task_id},
                    )
                next_projection = replace(
                    next_projection,
                    tasks=tuple(
                        replace(item, status=TaskLifecycle.SKIPPED, active_instance_id=None, failure_reason_code="plan_patch_skip")
                        if item.task_id == task_id else item
                        for item in next_projection.tasks
                    ),
                    last_sequence=next_projection.last_sequence + 1,
                )
                events.append(
                    TaskPlanEvent(
                        "TASK_SKIPPED",
                        run_id=plan.run_id,
                        workflow_id=plan.workflow_id,
                        stage_id=plan.stage_id,
                        graph_checksum=plan.graph_checksum,
                        plan_id=plan.plan_id,
                        plan_version=plan.version,
                        task_id=task_id,
                        reason_code="plan_patch_skip",
                        input_checksum=plan.plan_checksum,
                        sequence=next_projection.last_sequence,
                    )
                )
            self._plans[(plan.run_id, plan.stage_id, plan.version)] = plan
            for event in events:
                self._append_event(event)
            self._projections[(plan.run_id, plan.stage_id)] = next_projection
            return plan.plan_checksum

    def append_result(self, result: TaskResultRecord) -> str:
        if not isinstance(result, TaskResultRecord):
            raise TypeError("result must be TaskResultRecord")
        key = (result.run_id, result.stage_id, result.task_instance_id, result.attempt, result.plan_version)
        with self._lock:
            existing = self._results.get(key)
            if existing is not None:
                if existing.result_checksum != result.result_checksum:
                    raise HarnessValidationError("conflicting duplicate task result", code="task_plan_duplicate_result_conflict")
                return existing.result_checksum
            projection = self._projections.get((result.run_id, result.stage_id))
            if projection is None or projection.plan_id != result.plan_id or projection.plan_version != result.plan_version:
                raise HarnessValidationError("task result belongs to stale plan", code="task_plan_stale_result")
            plan = self._plans.get((result.run_id, result.stage_id, result.plan_version))
            if plan is None:
                raise HarnessValidationError("task result plan is unavailable", code="task_plan_stale_result")
            task = next((item for item in projection.tasks if item.task_id == result.task_id), None)
            if task is None:
                raise HarnessValidationError("task result references unknown task", code="task_plan_unknown_task")
            definition = next((item for item in plan.tasks if item.task_id == result.task_id), None)
            if definition is None or definition.task_definition_checksum != result.task_checksum:
                raise HarnessValidationError("task result definition checksum does not match accepted plan", code="task_plan_result_identity_mismatch")
            if definition.worker_ref != result.worker_ref:
                raise HarnessValidationError("task result worker binding does not match accepted plan", code="task_plan_wrong_binding")
            if result.binding_checksum != definition.binding_checksum:
                raise HarnessValidationError(
                    "task result binding checksum does not match accepted plan",
                    code="task_plan_wrong_binding",
                )
            if task.active_instance_id != result.task_instance_id or task.attempts != result.attempt:
                raise HarnessValidationError("task result belongs to a different attempt", code="task_plan_wrong_attempt")
            if task.status in {TaskLifecycle.SUCCEEDED, TaskLifecycle.SKIPPED}:
                raise HarnessValidationError("task already has a committed terminal result", code="task_plan_duplicate_result_conflict")
            _require_subagent_result_evidence(result, definition)
            _validate_result_usage(result, definition)
            if result.status is TaskLifecycle.SUCCEEDED:
                if result.output_schema_ref != definition.task.output_contract.schema_ref:
                    raise HarnessValidationError(
                        "task result output schema does not match accepted task",
                        code="task_plan_output_schema_mismatch",
                    )
                if result.output_roles != (definition.output_role,):
                    raise HarnessValidationError(
                        "task result output role does not match accepted task",
                        code="task_plan_output_role_mismatch",
                    )
                if not result.output_roles:
                    raise HarnessValidationError("successful task result requires an output role", code="task_plan_result_invalid")
                reference = TaskResultReference(result_ref=result.result_ref or "task-result:" + result.result_checksum, result_checksum=result.result_checksum, output_role=result.output_roles[0], output_schema_ref=result.output_schema_ref)
                updated = replace(task, status=TaskLifecycle.SUCCEEDED, attempts=result.attempt, active_instance_id=None, result=reference)
                result_event_type = "TASK_RESULT_ACCEPTED"
                terminal_event_type = "TASK_COMPLETED"
            else:
                updated = replace(task, status=TaskLifecycle.FAILED, attempts=result.attempt, active_instance_id=result.task_instance_id, failure_reason_code=result.error_code or "task_failed")
                result_event_type = "TASK_RESULT_REJECTED"
                terminal_event_type = "TASK_FAILED"
            tasks = tuple(updated if item.task_id == result.task_id else item for item in projection.tasks)
            result_sequence = self._next_sequence(result.run_id, result.stage_id)
            terminal_sequence = result_sequence + 1
            graph_checksum = self._graph_checksum(result.run_id, result.stage_id)
            result_event = _result_event(
                result,
                result_event_type,
                result_sequence,
                graph_checksum=graph_checksum,
            )
            terminal_event = _terminal_result_event(
                result,
                terminal_event_type,
                terminal_sequence,
                graph_checksum=graph_checksum,
            )
            settled_budget = _settle_result_budget(
                projection.consumed_budget,
                definition,
                result,
            )
            next_projection = replace(
                projection,
                tasks=tasks,
                consumed_budget=settled_budget,
                last_sequence=terminal_sequence,
            )

            # The in-memory implementation models the same atomic boundary as
            # the durable adapter: result evidence, both causal events, and the
            # authoritative projection become visible together.
            self._results[key] = result
            self._append_event(result_event)
            self._append_event(terminal_event)
            self._projections[(result.run_id, result.stage_id)] = next_projection
            return result.result_checksum

    def load_projection(self, run_id: str, stage_id: str) -> TaskPlanProjection:
        key = (identifier(run_id, "run_id"), identifier(stage_id, "stage_id"))
        with self._lock:
            projection = self._projections.get(key)
            if projection is None:
                raise HarnessValidationError("TaskPlan projection is missing", code="task_plan_projection_missing", details={"run_id": key[0], "stage_id": key[1]})
            return projection

    def read_events(self, run_id: str, stage_id: str) -> tuple[TaskPlanEvent, ...]:
        with self._lock:
            return tuple(self._events.get((run_id, stage_id), ()))

    def update_projection(self, projection: TaskPlanProjection) -> None:
        if not isinstance(projection, TaskPlanProjection):
            raise TypeError("projection must be TaskPlanProjection")
        with self._lock:
            current = self._projections.get((projection.run_id, projection.stage_id))
            if current is None:
                raise HarnessValidationError(
                    "TaskPlan projection update requires a durable accepted baseline",
                    code="task_plan_projection_missing",
                )
            if current is not None:
                if projection.plan_id != current.plan_id or projection.plan_version != current.plan_version or projection.plan_checksum != current.plan_checksum:
                    raise HarnessValidationError("projection plan identity changed", code="task_plan_projection_mismatch")
                if projection.last_sequence < current.last_sequence:
                    raise HarnessValidationError("projection sequence moved backwards", code="task_plan_sequence_conflict")
            self._projections[(projection.run_id, projection.stage_id)] = projection

    def results_for(self, run_id: str, stage_id: str, plan_id: str, plan_version: int) -> tuple[TaskResultRecord, ...]:
        with self._lock:
            current_plan = self._plans.get((run_id, stage_id, plan_version))
            valid_task_ids = {
                item.task_id
                for item in (self._projections.get((run_id, stage_id)).tasks if self._projections.get((run_id, stage_id)) else ())
                if item.status is TaskLifecycle.SUCCEEDED
            }
            matching = [
                item
                for item in self._results.values()
                if item.run_id == run_id
                and item.stage_id == stage_id
                and item.task_id in valid_task_ids
                and (item.plan_id == plan_id and item.plan_version == plan_version or current_plan is not None and _plan_contains_task_version(self._plans, current_plan, item))
            ]
            unique: dict[str, TaskResultRecord] = {}
            for item in matching:
                unique.setdefault(item.task_id, item)
            return tuple(sorted(unique.values(), key=lambda item: (item.task_id, item.attempt, item.result_checksum)))

    def append_event(self, event: TaskPlanEvent) -> str:
        if not isinstance(event, TaskPlanEvent):
            raise TypeError("event must be TaskPlanEvent")
        with self._lock:
            current = self._next_sequence(event.run_id, event.stage_id)
            if event.sequence != current:
                raise HarnessValidationError("event sequence is not monotonic", code="task_plan_sequence_conflict", details={"expected": current, "actual": event.sequence})
            self._append_event(event)
            key = (event.run_id, event.stage_id)
            projection = self._projections.get(key)
            if projection is not None:
                self._projections[key] = replace(
                    projection,
                    last_sequence=event.sequence,
                )
            return event.event_checksum

    def commit_event(
        self,
        event: TaskPlanEvent,
        projection: TaskPlanProjection,
    ) -> str:
        """Atomically append one decision event and its resulting projection."""

        if not isinstance(event, TaskPlanEvent):
            raise TypeError("event must be TaskPlanEvent")
        if not isinstance(projection, TaskPlanProjection):
            raise TypeError("projection must be TaskPlanProjection")
        key = (event.run_id, event.stage_id)
        with self._lock:
            current = self._projections.get(key)
            if current is None:
                raise HarnessValidationError(
                    "TaskPlan transition requires an accepted projection",
                    code="task_plan_projection_missing",
                )
            expected_sequence = self._next_sequence(event.run_id, event.stage_id)
            if event.sequence != expected_sequence:
                raise HarnessValidationError(
                    "event sequence is not monotonic",
                    code="task_plan_sequence_conflict",
                    details={"expected": expected_sequence, "actual": event.sequence},
                )
            _require_projection_transition_identity(current, projection)
            if projection.last_sequence != event.sequence:
                raise HarnessValidationError(
                    "projection sequence must match its causal event",
                    code="task_plan_sequence_conflict",
                    details={
                        "event_sequence": event.sequence,
                        "projection_sequence": projection.last_sequence,
                    },
                )
            self._append_event(event)
            self._projections[key] = projection
            return event.event_checksum

    def candidate(self, candidate_ref: str) -> PlanCandidate | None:
        with self._lock:
            return self._candidates.get(candidate_ref)

    def plan(self, run_id: str, stage_id: str, version: int | None = None) -> ValidatedTaskPlan | None:
        with self._lock:
            if version is not None:
                return self._plans.get((run_id, stage_id, version))
            return self._current_plan(run_id, stage_id)

    def _current_plan(self, run_id: str, stage_id: str) -> ValidatedTaskPlan | None:
        plans = [plan for (candidate_run, candidate_stage, _), plan in self._plans.items() if candidate_run == run_id and candidate_stage == stage_id]
        return max(plans, key=lambda item: item.version) if plans else None

    def _graph_checksum(self, run_id: str, stage_id: str) -> str:
        plan = self._current_plan(run_id, stage_id)
        return plan.graph_checksum if plan else "sha256:" + "0" * 64

    def _next_sequence(self, run_id: str, stage_id: str) -> int:
        return len(self._events.get((run_id, stage_id), ())) + 1

    def _append_event(self, event: TaskPlanEvent) -> None:
        self._events.setdefault((event.run_id, event.stage_id), []).append(event)


def _projection_for_plan(plan: ValidatedTaskPlan, *, sequence: int, previous: TaskPlanProjection | None = None) -> TaskPlanProjection:
    previous_by_id = {item.task_id: item for item in previous.tasks} if previous is not None else {}
    states = []
    for item in plan.tasks:
        old = previous_by_id.get(item.task_id)
        if old is not None and old.task_definition_checksum == item.task_definition_checksum and old.status in {TaskLifecycle.SUCCEEDED, TaskLifecycle.FAILED, TaskLifecycle.SKIPPED}:
            states.append(old)
        else:
            states.append(TaskProjection(task_id=item.task_id, task_definition_checksum=item.task_definition_checksum, status=TaskLifecycle.PENDING))
    return TaskPlanProjection(
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_checksum=plan.plan_checksum,
        policy_ref=plan.policy_ref,
        tasks=tuple(states),
        consumed_budget=previous.consumed_budget if previous is not None else {},
        last_sequence=sequence,
    )


def _plan_contains_task_version(plans: Mapping[tuple[str, str, int], ValidatedTaskPlan], current: ValidatedTaskPlan, result: TaskResultRecord) -> bool:
    if result.plan_id == current.plan_id and result.plan_version == current.version:
        return True
    if result.run_id != current.run_id or result.stage_id != current.stage_id or result.plan_version >= current.version:
        return False
    ancestor = plans.get((current.run_id, current.stage_id, result.plan_version))
    if ancestor is None:
        return False
    return any(item.task_id == result.task_id and item.task_definition_checksum == result.task_checksum for item in ancestor.tasks)


def _candidate_event(candidate: PlanCandidate, event_type: str, sequence: int, *, reason_code: str | None = None) -> TaskPlanEvent:
    return TaskPlanEvent(
        event_type,
        **_task_plan_event_identity_kwargs(candidate),
        input_checksum=candidate.candidate_checksum,
        reason_code=reason_code,
        payload={"candidate_ref": candidate.candidate_checksum},
        sequence=sequence,
    )


def _plan_event(plan: ValidatedTaskPlan, event_type: str, sequence: int) -> TaskPlanEvent:
    return TaskPlanEvent(
        event_type,
        **_task_plan_event_identity_kwargs(plan),
        plan_id=plan.plan_id,
        plan_version=plan.version,
        input_checksum=plan.plan_checksum,
        payload={"plan_ref": plan.plan_checksum, "policy_ref": plan.policy_ref},
        sequence=sequence,
    )


def _task_plan_event_identity_kwargs(
    value: PlanCandidate | ValidatedTaskPlan,
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "run_id": value.run_id,
        "workflow_id": value.workflow_id,
        "stage_id": value.stage_id,
        "graph_checksum": value.graph_checksum,
        "schema_version": (
            TASK_PLAN_EVENT_SCHEMA_V2
            if value.is_graph_only
            else TASK_PLAN_EVENT_SCHEMA_V1
        ),
    }
    if value.is_graph_only:
        identity.update(
            {
                name: getattr(value, name)
                for name in _GRAPH_ONLY_TASK_PLAN_EVENT_IDENTITY_FIELDS
            }
        )
    return identity


def _result_event(result: TaskResultRecord, event_type: str, sequence: int, *, graph_checksum: str) -> TaskPlanEvent:
    return TaskPlanEvent(
        event_type,
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        stage_id=result.stage_id,
        graph_checksum=graph_checksum,
        plan_id=result.plan_id,
        plan_version=result.plan_version,
        task_id=result.task_id,
        task_instance_id=result.task_instance_id,
        attempt=result.attempt,
        input_checksum=result.task_checksum,
        output_refs=result.output_refs,
        reason_code=result.error_code,
        payload={
            "result_ref": result.result_ref,
            "result_checksum": result.result_checksum,
            "gate_refs": list(result.verified_gate_refs),
            "gate_evidence_refs": list(result.gate_evidence_refs),
            "transcript_ref": result.transcript_ref,
            "transcript_checksum": result.transcript_checksum,
            "subagent_output_ref": result.subagent_output_ref,
            "subagent_output_checksum": result.subagent_output_checksum,
        },
        sequence=sequence,
    )


def _terminal_result_event(
    result: TaskResultRecord,
    event_type: str,
    sequence: int,
    *,
    graph_checksum: str,
) -> TaskPlanEvent:
    return TaskPlanEvent(
        event_type,
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        stage_id=result.stage_id,
        graph_checksum=graph_checksum,
        plan_id=result.plan_id,
        plan_version=result.plan_version,
        task_id=result.task_id,
        task_instance_id=result.task_instance_id,
        attempt=result.attempt,
        input_checksum=result.result_checksum,
        output_refs=result.output_refs,
        reason_code=result.error_code,
        payload={
            "result_ref": result.result_ref,
            "result_checksum": result.result_checksum,
            "gate_refs": list(result.verified_gate_refs),
            "gate_evidence_refs": list(result.gate_evidence_refs),
            "transcript_ref": result.transcript_ref,
            "transcript_checksum": result.transcript_checksum,
            "subagent_output_ref": result.subagent_output_ref,
            "subagent_output_checksum": result.subagent_output_checksum,
        },
        sequence=sequence,
    )


def _validate_result_usage(result: TaskResultRecord, definition: Any) -> None:
    aliases = {
        "turns": "max_turns",
        "tool_calls": "max_tool_calls",
        "memory_ops": "max_memory_ops",
        "output_tokens": "max_output_tokens",
        "max_turns": "max_turns",
        "max_tool_calls": "max_tool_calls",
        "max_memory_ops": "max_memory_ops",
        "max_output_tokens": "max_output_tokens",
    }
    for raw_name, raw_value in result.usage.items():
        name = aliases.get(str(raw_name))
        if name is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise HarnessValidationError(
                "task result usage must be a non-negative integer",
                code="task_plan_result_usage_invalid",
                details={"field": str(raw_name)},
            )
        limit = getattr(definition.normalized_budget, name)
        if raw_value > limit:
            raise HarnessValidationError(
                "task result usage exceeds the accepted task budget",
                code="task_plan_result_budget_exceeded",
                details={"field": str(raw_name), "used": raw_value, "limit": limit},
            )


def _require_subagent_result_evidence(
    result: TaskResultRecord,
    definition: Any,
) -> None:
    evidence = (
        result.transcript_ref,
        result.transcript_checksum,
        result.subagent_output_ref,
        result.subagent_output_checksum,
    )
    if definition.subagent_id is not None:
        if result.schema_version == TASK_PLAN_RESULT_SCHEMA_V1:
            raise HarnessValidationError(
                "legacy subagent result has no durable transcript evidence",
                code="subagent_transcript_legacy_unavailable",
            )
        if not all(item is not None for item in evidence):
            raise HarnessValidationError(
                "subagent task result requires durable transcript evidence",
                code="task_plan_subagent_evidence_required",
            )
    elif any(item is not None for item in evidence):
        raise HarnessValidationError(
            "non-subagent task result must not carry subagent evidence",
            code="task_plan_unexpected_subagent_evidence",
        )


def _settle_result_budget(
    snapshot: Mapping[str, Any],
    definition: Any,
    result: TaskResultRecord,
) -> dict[str, int]:
    budget = {
        str(key): int(value)
        for key, value in snapshot.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    usage_aliases = {
        "max_turns": ("turns", "max_turns"),
        "max_tool_calls": ("tool_calls", "max_tool_calls"),
        "max_memory_ops": ("memory_ops", "max_memory_ops"),
        "max_output_tokens": ("output_tokens", "max_output_tokens"),
    }
    for name, aliases in usage_aliases.items():
        reserved_key = f"reserved_{name}"
        consumed_key = f"consumed_{name}"
        reservation = getattr(definition.normalized_budget, name)
        current_reserved = int(budget.get(reserved_key, 0))
        if current_reserved < reservation:
            raise HarnessValidationError(
                "task result has no matching budget reservation",
                code="task_plan_budget_reservation_missing",
                details={"task_id": result.task_id, "field": name},
            )
        budget[reserved_key] = current_reserved - reservation
        supplied = next((result.usage[key] for key in aliases if key in result.usage), None)
        consumed = reservation if supplied is None else int(supplied)
        budget[consumed_key] = int(budget.get(consumed_key, 0)) + consumed
    return dict(sorted(budget.items()))


def _require_projection_transition_identity(
    current: TaskPlanProjection,
    proposed: TaskPlanProjection,
) -> None:
    identity_fields = (
        "run_id",
        "stage_id",
        "graph_checksum",
        "plan_id",
        "plan_version",
        "plan_checksum",
        "policy_ref",
    )
    if any(getattr(current, name) != getattr(proposed, name) for name in identity_fields):
        raise HarnessValidationError(
            "projection transition changed accepted plan identity",
            code="task_plan_projection_mismatch",
        )


__all__ = [
    "InMemoryTaskPlanStore",
    "TASK_PLAN_EVENT_SCHEMA",
    "TASK_PLAN_EVENT_SCHEMA_V1",
    "TASK_PLAN_EVENT_SCHEMA_V2",
    "TASK_PLAN_EVENT_SCHEMAS",
    "TASK_PLAN_EVENT_TYPES",
    "TaskPlanEvent",
    "TaskPlanStorePort",
    "TaskResultRecord",
]
