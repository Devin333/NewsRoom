from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self, cast

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    HarnessRetryPolicy,
    HarnessStepSpec,
    HarnessWorkerType,
)
from framework.harness.graph.canonical import (
    canonical_checksum,
    freeze_json,
)
from framework.harness.graph.dsl import (
    BoundedLoop,
    Choice,
    HarnessGraphExpression,
    HarnessGraphSpec,
    ParallelAll,
    ParallelAny,
    Sequence as GraphSequence,
    StepRef,
    VerifiedAggregation,
    Wait,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
)
from framework.harness.side_effects.models import (
    HarnessSideEffectHandlerReference,
    HarnessTerminalSideEffectPolicy,
)


MAX_GRAPH_DEFINITION_ACTIVITIES = 10_000
_GRAPH_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*\Z")
_GRAPH_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})
_EXACT_REFERENCE_PATTERN = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._:/+-]*)@([A-Za-z0-9][A-Za-z0-9._+-]*)\Z"
)
_EXACT_SCHEMA_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/+-]*/v[1-9][0-9]*\Z"
)
_TASK_PLAN_SUPPORT_REFERENCE_FIELDS = (
    "candidate_builder_ref",
    "capability_registry_ref",
    "gate_registry_ref",
    "aggregator_ref",
    "checkpoint_ref",
    "result_store_ref",
)
_TASK_PLAN_SUPPORT_FIELDS = frozenset(
    (*_TASK_PLAN_SUPPORT_REFERENCE_FIELDS, "event_schema")
)
_TYPED_LEAF_WORKER_TYPES = frozenset(
    HarnessWorkerType(kind.value) for kind in HarnessLeafActivityKind
)
_GRAPH_DEFINITION_WORKER_TYPES = _TYPED_LEAF_WORKER_TYPES | {
    HarnessWorkerType.TASK_PLAN,
}


@dataclass(frozen=True, slots=True)
class HarnessGraphLeafBinding:
    """Checksum-bound selection of one exact typed leaf registration."""

    activity_id: str
    leaf_activity_kind: HarnessLeafActivityKind | str
    worker_ref: HarnessContractReference | Mapping[str, Any]
    activity_ref: HarnessContractReference | Mapping[str, Any]

    def __post_init__(self) -> None:
        activity_id = _identifier(self.activity_id, "leaf_binding.activity_id")
        try:
            leaf_activity_kind = HarnessLeafActivityKind(
                self.leaf_activity_kind
            )
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "Graph leaf activity kind is invalid",
                code="invalid_graph_leaf_activity_binding",
            ) from exc
        worker_ref = _contract_reference(
            self.worker_ref,
            expected_kind=HarnessContractKind.WORKER,
            field="leaf_binding.worker_ref",
        )
        activity_ref = _contract_reference(
            self.activity_ref,
            expected_kind=HarnessContractKind.ACTIVITY,
            field="leaf_binding.activity_ref",
        )
        object.__setattr__(self, "activity_id", activity_id)
        object.__setattr__(self, "leaf_activity_kind", leaf_activity_kind)
        object.__setattr__(self, "worker_ref", worker_ref)
        object.__setattr__(self, "activity_ref", activity_ref)

    @property
    def expected_worker_type(self) -> HarnessWorkerType:
        return HarnessWorkerType(self.leaf_activity_kind.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "leaf_activity_kind": self.leaf_activity_kind.value,
            "worker_ref": self.worker_ref.to_dict(),
            "activity_ref": self.activity_ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessGraphLeafBinding":
        payload = _exact_mapping(
            value,
            {
                "activity_id",
                "leaf_activity_kind",
                "worker_ref",
                "activity_ref",
            },
            "Graph leaf activity binding",
        )
        return cls(
            activity_id=payload["activity_id"],
            leaf_activity_kind=payload["leaf_activity_kind"],
            worker_ref=payload["worker_ref"],
            activity_ref=payload["activity_ref"],
        )


@dataclass(frozen=True, slots=True)
class HarnessGraphTaskPlanStageBinding:
    """Checksum-bound declaration for one internal dynamic TaskPlan stage."""

    activity_id: str
    worker_ref: HarnessContractReference | Mapping[str, Any]
    activity_ref: HarnessContractReference | Mapping[str, Any]
    policy_ref: str
    task_plan_schema: str
    required_output_roles: tuple[str, ...]
    support_refs: Mapping[str, str]

    def __post_init__(self) -> None:
        activity_id = _identifier(
            self.activity_id,
            "task_plan_binding.activity_id",
        )
        worker_ref = _contract_reference(
            self.worker_ref,
            expected_kind=HarnessContractKind.WORKER,
            field="task_plan_binding.worker_ref",
            invalid_code="invalid_graph_task_plan_stage_binding",
            kind_mismatch_code="graph_task_plan_contract_kind_mismatch",
        )
        activity_ref = _contract_reference(
            self.activity_ref,
            expected_kind=HarnessContractKind.ACTIVITY,
            field="task_plan_binding.activity_ref",
            invalid_code="invalid_graph_task_plan_stage_binding",
            kind_mismatch_code="graph_task_plan_contract_kind_mismatch",
        )
        policy_ref = _exact_reference_text(
            self.policy_ref,
            "task_plan_binding.policy_ref",
        )
        task_plan_schema = _exact_schema(
            self.task_plan_schema,
            "task_plan_binding.task_plan_schema",
        )
        required_output_roles = _unique_text_tuple(
            self.required_output_roles,
            "task_plan_binding.required_output_roles",
        )
        support_refs = _task_plan_support_refs(self.support_refs)
        object.__setattr__(self, "activity_id", activity_id)
        object.__setattr__(self, "worker_ref", worker_ref)
        object.__setattr__(self, "activity_ref", activity_ref)
        object.__setattr__(self, "policy_ref", policy_ref)
        object.__setattr__(self, "task_plan_schema", task_plan_schema)
        object.__setattr__(
            self,
            "required_output_roles",
            required_output_roles,
        )
        object.__setattr__(self, "support_refs", support_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "worker_ref": self.worker_ref.to_dict(),
            "activity_ref": self.activity_ref.to_dict(),
            "policy_ref": self.policy_ref,
            "task_plan_schema": self.task_plan_schema,
            "required_output_roles": list(self.required_output_roles),
            "support_refs": dict(self.support_refs),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "HarnessGraphTaskPlanStageBinding":
        payload = _exact_mapping(
            value,
            {
                "activity_id",
                "worker_ref",
                "activity_ref",
                "policy_ref",
                "task_plan_schema",
                "required_output_roles",
                "support_refs",
            },
            "Graph TaskPlan stage binding",
        )
        return cls(
            activity_id=payload["activity_id"],
            worker_ref=payload["worker_ref"],
            activity_ref=payload["activity_ref"],
            policy_ref=payload["policy_ref"],
            task_plan_schema=payload["task_plan_schema"],
            required_output_roles=_unique_text_tuple(
                payload["required_output_roles"],
                "task_plan_binding.required_output_roles",
            ),
            support_refs=_mapping(
                payload["support_refs"],
                "task_plan_binding.support_refs",
            ),
        )


class HarnessGraphRepairTrigger(StrEnum):
    """Deterministic failures that may activate an explicit repair node."""

    WORKER_FAILURE_AFTER_RETRY_EXHAUSTION = (
        "worker_failure_after_retry_exhaustion"
    )
    VERIFICATION_FAILURE = "verification_failure"


@dataclass(frozen=True, slots=True)
class HarnessGraphRepairBinding:
    """Checksum-bound repair route owned by the outer Graph declaration."""

    binding_id: str
    source_node_id: str
    repair_node_id: str
    repair_activity_id: str
    triggers: tuple[HarnessGraphRepairTrigger | str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "binding_id",
            _identifier(self.binding_id, "repair_binding.binding_id"),
        )
        object.__setattr__(
            self,
            "source_node_id",
            _identifier(self.source_node_id, "repair_binding.source_node_id"),
        )
        object.__setattr__(
            self,
            "repair_node_id",
            _identifier(self.repair_node_id, "repair_binding.repair_node_id"),
        )
        object.__setattr__(
            self,
            "repair_activity_id",
            _identifier(
                self.repair_activity_id,
                "repair_binding.repair_activity_id",
            ),
        )
        object.__setattr__(self, "triggers", _repair_triggers(self.triggers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_node_id": self.source_node_id,
            "repair_node_id": self.repair_node_id,
            "repair_activity_id": self.repair_activity_id,
            "triggers": [trigger.value for trigger in self.triggers],
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "HarnessGraphRepairBinding":
        payload = _exact_mapping(
            value,
            {
                "binding_id",
                "source_node_id",
                "repair_node_id",
                "repair_activity_id",
                "triggers",
            },
            "Graph repair binding",
        )
        return cls(
            binding_id=payload["binding_id"],
            source_node_id=payload["source_node_id"],
            repair_node_id=payload["repair_node_id"],
            repair_activity_id=payload["repair_activity_id"],
            triggers=_repair_triggers(payload["triggers"]),
        )


@dataclass(frozen=True, slots=True)
class HarnessGraphDefinition:
    """Immutable, canonical Graph declaration before compiler preflight."""

    graph_id: str
    graph_version: str
    root: HarnessGraphSpec | Mapping[str, Any]
    activities: tuple[HarnessStepSpec, ...]
    leaf_activity_bindings: tuple[HarnessGraphLeafBinding, ...]
    task_plan_stage_bindings: tuple[HarnessGraphTaskPlanStageBinding, ...]
    repair_bindings: tuple[HarnessGraphRepairBinding, ...]
    terminal_side_effect_policy: (
        HarnessTerminalSideEffectPolicy | Mapping[str, Any]
    )
    schema_version: str = HARNESS_GRAPH_DEFINITION_SCHEMA
    definition_checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        graph_id = _identifier(self.graph_id, "graph_id")
        graph_version = _exact_version(self.graph_version, "graph_version")
        root = self.root
        if not isinstance(root, HarnessGraphSpec):
            if not isinstance(root, Mapping):
                raise HarnessValidationError(
                    "root must be a HarnessGraphSpec",
                    code="invalid_graph_definition",
                )
            root = HarnessGraphSpec.from_dict(root)
        if root.graph_id != graph_id:
            raise HarnessValidationError(
                "Graph definition identity must match its root Graph",
                code="graph_definition_identity_mismatch",
                details={
                    "definition_graph_id": graph_id,
                    "root_graph_id": root.graph_id,
                },
            )
        activities = _activities(self.activities)
        leaf_activity_bindings = _leaf_activity_bindings(
            self.leaf_activity_bindings
        )
        task_plan_stage_bindings = _task_plan_stage_bindings(
            self.task_plan_stage_bindings
        )
        repair_bindings = _repair_bindings(self.repair_bindings)
        policy = self.terminal_side_effect_policy
        if not isinstance(policy, HarnessTerminalSideEffectPolicy):
            if not isinstance(policy, Mapping):
                raise HarnessValidationError(
                    "terminal_side_effect_policy must be a Harness policy",
                    code="invalid_graph_definition",
                )
            policy = HarnessTerminalSideEffectPolicy.from_dict(policy)
        if self.schema_version != HARNESS_GRAPH_DEFINITION_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph definition schema",
                code="unsupported_graph_definition_schema",
                details={"schema_version": str(self.schema_version)},
            )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "graph_version", graph_version)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "activities", activities)
        object.__setattr__(
            self,
            "leaf_activity_bindings",
            leaf_activity_bindings,
        )
        object.__setattr__(
            self,
            "task_plan_stage_bindings",
            task_plan_stage_bindings,
        )
        object.__setattr__(self, "repair_bindings", repair_bindings)
        object.__setattr__(self, "terminal_side_effect_policy", policy)
        expected = canonical_checksum(self.checksum_projection())
        if self.definition_checksum is not None:
            supplied = _checksum(
                self.definition_checksum,
                "definition_checksum",
            )
            if supplied != expected:
                raise HarnessValidationError(
                    "Graph definition checksum does not match canonical content",
                    code="graph_definition_checksum_mismatch",
                )
        object.__setattr__(self, "definition_checksum", expected)
        _validate_leaf_activity_bindings(
            leaf_activity_bindings,
            activities=activities,
        )
        _validate_task_plan_stage_bindings(
            task_plan_stage_bindings,
            activities=activities,
        )
        _validate_activity_repair_routing(activities)
        _validate_repair_bindings(
            repair_bindings,
            root=root,
            activities=activities,
        )

    @property
    def activity_ids(self) -> tuple[str, ...]:
        return tuple(activity.step_id for activity in self.activities)

    def activity(self, activity_id: str) -> HarnessStepSpec | None:
        normalized = _identifier(activity_id, "activity_id")
        for activity in self.activities:
            if activity.step_id == normalized:
                return activity
        return None

    def leaf_activity_binding(
        self,
        activity_id: str,
    ) -> HarnessGraphLeafBinding | None:
        normalized = _identifier(activity_id, "activity_id")
        for binding in self.leaf_activity_bindings:
            if binding.activity_id == normalized:
                return binding
        return None

    def task_plan_stage_binding(
        self,
        activity_id: str,
    ) -> HarnessGraphTaskPlanStageBinding | None:
        normalized = _identifier(activity_id, "activity_id")
        for binding in self.task_plan_stage_bindings:
            if binding.activity_id == normalized:
                return binding
        return None

    def repair_binding(
        self,
        binding_id: str,
    ) -> HarnessGraphRepairBinding | None:
        normalized = _identifier(binding_id, "binding_id")
        for binding in self.repair_bindings:
            if binding.binding_id == normalized:
                return binding
        return None

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "root": self.root.to_dict(),
            "activities": [activity.to_dict() for activity in self.activities],
            "leaf_activity_bindings": [
                binding.to_dict() for binding in self.leaf_activity_bindings
            ],
            "task_plan_stage_bindings": [
                binding.to_dict() for binding in self.task_plan_stage_bindings
            ],
            "repair_bindings": [
                binding.to_dict() for binding in self.repair_bindings
            ],
            "terminal_side_effect_policy": (
                self.terminal_side_effect_policy.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "definition_checksum": self.definition_checksum,
        }

    def verify_integrity(self) -> None:
        if self.definition_checksum != canonical_checksum(
            self.checksum_projection()
        ):
            raise HarnessValidationError(
                "Graph definition checksum does not match canonical content",
                code="graph_definition_checksum_mismatch",
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_id",
                "graph_version",
                "root",
                "activities",
                "leaf_activity_bindings",
                "task_plan_stage_bindings",
                "repair_bindings",
                "terminal_side_effect_policy",
                "definition_checksum",
            },
            "Graph definition",
        )
        return cls(
            schema_version=payload["schema_version"],
            graph_id=payload["graph_id"],
            graph_version=payload["graph_version"],
            root=_mapping(payload["root"], "root"),
            activities=tuple(
                _activity_from_dict(item)
                for item in _mapping_array(
                    payload["activities"],
                    "activities",
                )
            ),
            leaf_activity_bindings=tuple(
                HarnessGraphLeafBinding.from_dict(item)
                for item in _mapping_array(
                    payload["leaf_activity_bindings"],
                    "leaf_activity_bindings",
                )
            ),
            task_plan_stage_bindings=tuple(
                HarnessGraphTaskPlanStageBinding.from_dict(item)
                for item in _mapping_array(
                    payload["task_plan_stage_bindings"],
                    "task_plan_stage_bindings",
                )
            ),
            repair_bindings=tuple(
                HarnessGraphRepairBinding.from_dict(item)
                for item in _mapping_array(
                    payload["repair_bindings"],
                    "repair_bindings",
                )
            ),
            terminal_side_effect_policy=_mapping(
                payload["terminal_side_effect_policy"],
                "terminal_side_effect_policy",
            ),
            definition_checksum=payload["definition_checksum"],
        )


class HarnessGraphDefinitionReader:
    """Strict Graph-only reader with no legacy declaration upcast path."""

    def read(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessGraphDefinition:
        if source_schema != HARNESS_GRAPH_DEFINITION_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph definition schema",
                code="unsupported_graph_definition_schema",
                details={"schema_version": str(source_schema)},
            )
        definition = HarnessGraphDefinition.from_dict(payload)
        if definition.schema_version != source_schema:
            raise HarnessValidationError(
                "Graph definition payload schema does not match reader schema",
                code="graph_definition_schema_mismatch",
            )
        return definition

    def read_for_execution(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessGraphDefinition:
        return self.read(payload, source_schema=source_schema)


def _activities(values: Sequence[HarnessStepSpec]) -> tuple[HarnessStepSpec, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values,
        Sequence,
    ):
        raise HarnessValidationError(
            "activities must be an array",
            code="invalid_graph_definition",
        )
    if not values or len(values) > MAX_GRAPH_DEFINITION_ACTIVITIES:
        raise HarnessValidationError(
            "Graph definition activity count is outside its bound",
            code="invalid_graph_definition",
        )
    if any(not isinstance(value, HarnessStepSpec) for value in values):
        raise HarnessValidationError(
            "activities must contain HarnessStepSpec values",
            code="invalid_graph_definition",
        )
    snapshots = tuple(
        sorted(
            (_activity_snapshot(value) for value in values),
            key=lambda item: item.step_id,
        )
    )
    identities = tuple(activity.step_id for activity in snapshots)
    if len(identities) != len(set(identities)):
        raise HarnessValidationError(
            "Graph definition activity identities must be unique",
            code="graph_duplicate_identity",
            details={"field": "activities"},
        )
    return snapshots


def _activity_snapshot(activity: HarnessStepSpec) -> HarnessStepSpec:
    snapshot = HarnessStepSpec(
        step_id=activity.step_id,
        worker_type=activity.worker_type,
        input_keys=tuple(activity.input_keys),
        output_key=activity.output_key,
        retry_policy=activity.retry_policy,
        quality_gate=activity.quality_gate,
        metadata={},
        side_effect_handler=activity.side_effect_handler,
    )
    object.__setattr__(
        snapshot,
        "metadata",
        freeze_json(activity.metadata, f"activity.{activity.step_id}.metadata"),
    )
    return snapshot


def _leaf_activity_bindings(
    values: Sequence[HarnessGraphLeafBinding],
) -> tuple[HarnessGraphLeafBinding, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values,
        Sequence,
    ):
        raise HarnessValidationError(
            "leaf_activity_bindings must be an array",
            code="invalid_graph_definition",
        )
    if len(values) > MAX_GRAPH_DEFINITION_ACTIVITIES or any(
        not isinstance(value, HarnessGraphLeafBinding) for value in values
    ):
        raise HarnessValidationError(
            "leaf_activity_bindings must contain HarnessGraphLeafBinding values",
            code="invalid_graph_definition",
        )
    snapshots = tuple(
        sorted(
            (
                HarnessGraphLeafBinding.from_dict(value.to_dict())
                for value in values
            ),
            key=lambda item: item.activity_id,
        )
    )
    binding_ids = tuple(binding.activity_id for binding in snapshots)
    if len(binding_ids) != len(set(binding_ids)):
        raise HarnessValidationError(
            "Graph leaf activity binding identities must be unique",
            code="graph_duplicate_identity",
            details={"field": "leaf_activity_bindings"},
        )
    return snapshots


def _task_plan_stage_bindings(
    values: Sequence[HarnessGraphTaskPlanStageBinding],
) -> tuple[HarnessGraphTaskPlanStageBinding, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values,
        Sequence,
    ):
        raise HarnessValidationError(
            "task_plan_stage_bindings must be an array",
            code="invalid_graph_definition",
        )
    if len(values) > MAX_GRAPH_DEFINITION_ACTIVITIES or any(
        not isinstance(value, HarnessGraphTaskPlanStageBinding)
        for value in values
    ):
        raise HarnessValidationError(
            "task_plan_stage_bindings must contain "
            "HarnessGraphTaskPlanStageBinding values",
            code="invalid_graph_definition",
        )
    snapshots = tuple(
        sorted(
            (
                HarnessGraphTaskPlanStageBinding.from_dict(value.to_dict())
                for value in values
            ),
            key=lambda item: item.activity_id,
        )
    )
    binding_ids = tuple(binding.activity_id for binding in snapshots)
    if len(binding_ids) != len(set(binding_ids)):
        raise HarnessValidationError(
            "Graph TaskPlan stage binding identities must be unique",
            code="graph_duplicate_identity",
            details={"field": "task_plan_stage_bindings"},
        )
    return snapshots


def _repair_bindings(
    values: Sequence[HarnessGraphRepairBinding],
) -> tuple[HarnessGraphRepairBinding, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values,
        Sequence,
    ):
        raise HarnessValidationError(
            "repair_bindings must be an array",
            code="invalid_graph_definition",
        )
    if len(values) > MAX_GRAPH_DEFINITION_ACTIVITIES or any(
        not isinstance(value, HarnessGraphRepairBinding) for value in values
    ):
        raise HarnessValidationError(
            "repair_bindings must contain HarnessGraphRepairBinding values",
            code="invalid_graph_definition",
        )
    snapshots = tuple(
        sorted(
            (
                HarnessGraphRepairBinding.from_dict(value.to_dict())
                for value in values
            ),
            key=lambda item: item.binding_id,
        )
    )
    binding_ids = tuple(binding.binding_id for binding in snapshots)
    duplicate_binding_ids = sorted(
        identity
        for identity, count in Counter(binding_ids).items()
        if count > 1
    )
    if duplicate_binding_ids:
        raise HarnessValidationError(
            "Graph repair binding identities must be unique",
            code="graph_duplicate_identity",
            details={
                "field": "repair_bindings.binding_id",
                "duplicates": duplicate_binding_ids,
            },
        )
    return snapshots


def _validate_leaf_activity_bindings(
    bindings: tuple[HarnessGraphLeafBinding, ...],
    *,
    activities: tuple[HarnessStepSpec, ...],
) -> None:
    binding_ids = tuple(binding.activity_id for binding in bindings)

    activities_by_id = {activity.step_id: activity for activity in activities}
    unsupported = {
        activity.step_id: activity.worker_type.value
        for activity in activities
        if activity.worker_type not in _GRAPH_DEFINITION_WORKER_TYPES
    }
    if unsupported:
        raise HarnessValidationError(
            "Graph definition contains unsupported leaf worker types",
            code="graph_unsupported_leaf_worker_type",
            details={"activities": dict(sorted(unsupported.items()))},
        )

    unknown = sorted(set(binding_ids).difference(activities_by_id))
    expected = {
        activity.step_id
        for activity in activities
        if activity.worker_type in _TYPED_LEAF_WORKER_TYPES
    }
    actual = set(binding_ids)
    missing = sorted(expected.difference(actual))
    unexpected = sorted(actual.difference(expected))
    if unknown or missing or unexpected:
        raise HarnessValidationError(
            "Graph typed leaf binding coverage does not match its activities",
            code="graph_leaf_activity_binding_coverage_mismatch",
            details={
                "missing": missing,
                "unexpected": unexpected,
                "unknown": unknown,
            },
        )

    for binding in bindings:
        activity = activities_by_id[binding.activity_id]
        if binding.expected_worker_type is not activity.worker_type:
            raise HarnessValidationError(
                "Graph leaf activity kind does not match its worker type",
                code="graph_leaf_activity_kind_mismatch",
                details={
                    "activity_id": binding.activity_id,
                    "leaf_activity_kind": binding.leaf_activity_kind.value,
                    "expected_worker_type": binding.expected_worker_type.value,
                    "actual_worker_type": activity.worker_type.value,
                },
            )


def _validate_task_plan_stage_bindings(
    bindings: tuple[HarnessGraphTaskPlanStageBinding, ...],
    *,
    activities: tuple[HarnessStepSpec, ...],
) -> None:
    binding_ids = {binding.activity_id for binding in bindings}
    activities_by_id = {activity.step_id: activity for activity in activities}
    expected = {
        activity.step_id
        for activity in activities
        if activity.worker_type is HarnessWorkerType.TASK_PLAN
    }
    unknown = sorted(binding_ids.difference(activities_by_id))
    missing = sorted(expected.difference(binding_ids))
    unexpected = sorted(binding_ids.difference(expected))
    if unknown or missing or unexpected:
        raise HarnessValidationError(
            "Graph TaskPlan binding coverage does not match its activities",
            code="graph_task_plan_stage_binding_coverage_mismatch",
            details={
                "missing": missing,
                "unexpected": unexpected,
                "unknown": unknown,
            },
        )
    effectful = sorted(
        activity.step_id
        for activity in activities
        if activity.worker_type is HarnessWorkerType.TASK_PLAN
        and activity.side_effect_handler is not None
    )
    if effectful:
        raise HarnessValidationError(
            "Graph TaskPlan stages cannot own side-effect handlers",
            code="graph_task_plan_stage_side_effect_forbidden",
            details={"activities": effectful},
        )


def _validate_activity_repair_routing(
    activities: tuple[HarnessStepSpec, ...],
) -> None:
    activity_ids = sorted(
        activity.step_id
        for activity in activities
        if activity.retry_policy.repair_step_id is not None
    )
    if activity_ids:
        raise HarnessValidationError(
            "Graph activities cannot own repair routing",
            code="graph_activity_repair_routing_forbidden",
            details={"activities": activity_ids},
        )


def _validate_repair_bindings(
    bindings: tuple[HarnessGraphRepairBinding, ...],
    *,
    root: HarnessGraphSpec,
    activities: tuple[HarnessStepSpec, ...],
) -> None:
    root_node_ids, executable_node_ids = _root_node_identities(root.root)
    root_counts = Counter(root_node_ids)
    executable_counts = Counter(executable_node_ids)
    activities_by_id = {activity.step_id: activity for activity in activities}

    repair_node_ids = tuple(binding.repair_node_id for binding in bindings)
    duplicate_repair_node_ids = sorted(
        node_id
        for node_id, count in Counter(repair_node_ids).items()
        if count > 1
    )
    root_collisions = sorted(set(repair_node_ids).intersection(root_counts))
    if duplicate_repair_node_ids or root_collisions:
        raise HarnessValidationError(
            "Graph repair node identities must be independent and unique",
            code="graph_repair_node_identity_conflict",
            details={
                "duplicate_repair_node_ids": duplicate_repair_node_ids,
                "root_collisions": root_collisions,
            },
        )

    routes: dict[
        tuple[str, HarnessGraphRepairTrigger],
        HarnessGraphRepairBinding,
    ] = {}
    for binding in bindings:
        source_occurrences = executable_counts[binding.source_node_id]
        root_occurrences = root_counts[binding.source_node_id]
        if source_occurrences != 1 or root_occurrences != 1:
            if source_occurrences == 0:
                reason = (
                    "not_executable"
                    if root_occurrences > 0
                    else "unknown"
                )
            else:
                reason = "ambiguous"
            raise HarnessValidationError(
                "Graph repair source must identify one exact executable node",
                code="graph_repair_source_node_invalid",
                details={
                    "binding_id": binding.binding_id,
                    "source_node_id": binding.source_node_id,
                    "reason": reason,
                },
            )
        if binding.repair_activity_id not in activities_by_id:
            raise HarnessValidationError(
                "Graph repair activity must be registered by the definition",
                code="graph_repair_activity_unknown",
                details={
                    "binding_id": binding.binding_id,
                    "repair_activity_id": binding.repair_activity_id,
                },
            )
        for trigger in binding.triggers:
            route_key = (binding.source_node_id, trigger)
            previous = routes.get(route_key)
            if previous is not None:
                raise HarnessValidationError(
                    "Graph repair source trigger resolves to multiple targets",
                    code="graph_repair_trigger_ambiguous",
                    details={
                        "source_node_id": binding.source_node_id,
                        "trigger": trigger.value,
                        "binding_ids": sorted(
                            (previous.binding_id, binding.binding_id)
                        ),
                        "repair_node_ids": sorted(
                            (previous.repair_node_id, binding.repair_node_id)
                        ),
                    },
                )
            routes[route_key] = binding


def _root_node_identities(
    expression: HarnessGraphExpression,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    node_ids: list[str] = []
    executable_node_ids: list[str] = []

    def visit(current: HarnessGraphExpression) -> None:
        if isinstance(current, StepRef):
            node_id = current.node_id or current.step_id
            node_ids.append(node_id)
            executable_node_ids.append(node_id)
            return
        if isinstance(current, GraphSequence):
            for child in current.children:
                visit(child)
            return
        if isinstance(current, Choice):
            node_ids.extend((current.choice_id, f"{current.choice_id}:join"))
            for branch in current.branches:
                visit(branch.child)
            return
        if isinstance(current, ParallelAll):
            node_ids.extend((current.fork_id, current.join_id))
            for branch in current.branches:
                visit(branch.child)
            if current.merge is not None:
                node_ids.append(f"{current.join_id}:merge")
            if isinstance(current.merge, VerifiedAggregation):
                visit(current.merge.step)
            return
        if isinstance(current, ParallelAny):
            node_ids.extend((current.fork_id, current.join_id))
            for branch in current.branches:
                visit(branch.child)
            return
        if isinstance(current, BoundedLoop):
            node_ids.extend((current.loop_id, f"{current.loop_id}:join"))
            visit(current.body)
            if current.exit is not None:
                visit(current.exit)
            if current.exhaustion is not None:
                visit(current.exhaustion)
            return
        if isinstance(current, Wait):
            node_ids.append(current.wait_id)
            return
        raise AssertionError(
            f"unsupported HarnessGraphExpression: {type(current).__name__}"
        )

    visit(expression)
    return tuple(node_ids), tuple(executable_node_ids)


def _activity_from_dict(value: Mapping[str, Any]) -> HarnessStepSpec:
    payload = _exact_mapping(
        value,
        {
            "step_id",
            "worker_type",
            "input_keys",
            "output_key",
            "retry_policy",
            "quality_gate",
            "metadata",
        }
        | ({"side_effect_handler"} if "side_effect_handler" in value else set()),
        "Graph activity",
    )
    retry_payload = _exact_mapping(
        payload["retry_policy"],
        {
            "max_retries",
            "max_attempts",
            "effective_max_attempts",
            "retry_on_statuses",
            "backoff_seconds",
            "repair_step_id",
            "fail_fast_error_types",
        },
        "Graph activity retry policy",
    )
    retry_policy = HarnessRetryPolicy(
        max_retries=retry_payload["max_retries"],
        max_attempts=retry_payload["max_attempts"],
        retry_on_statuses=tuple(
            _text_array(retry_payload["retry_on_statuses"], "retry_on_statuses")
        ),
        backoff_seconds=retry_payload["backoff_seconds"],
        repair_step_id=retry_payload["repair_step_id"],
        fail_fast_error_types=tuple(
            _text_array(
                retry_payload["fail_fast_error_types"],
                "fail_fast_error_types",
            )
        ),
    )
    if retry_payload["effective_max_attempts"] != retry_policy.effective_max_attempts:
        raise HarnessValidationError(
            "Graph activity retry projection is inconsistent",
            code="invalid_graph_definition",
        )
    side_effect = payload.get("side_effect_handler")
    return HarnessStepSpec(
        step_id=payload["step_id"],
        worker_type=payload["worker_type"],
        input_keys=tuple(_text_array(payload["input_keys"], "input_keys")),
        output_key=payload["output_key"],
        retry_policy=retry_policy,
        quality_gate=payload["quality_gate"],
        metadata=dict(_mapping(payload["metadata"], "metadata")),
        side_effect_handler=(
            None
            if side_effect is None
            else HarnessSideEffectHandlerReference.parse(side_effect)
        ),
    )


def _identifier(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if _GRAPH_ID_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field_name} has an invalid format",
            code="invalid_graph_definition",
            details={"field": field_name},
        )
    return text


def _exact_version(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if (
        _GRAPH_VERSION_PATTERN.fullmatch(text) is None
        or text.casefold() in _MOVING_VERSIONS
    ):
        raise HarnessValidationError(
            f"{field_name} must be an exact version",
            code="graph_inexact_version_reference",
            details={"field": field_name, "version": text},
        )
    return text


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 checksum",
            code="invalid_graph_definition",
        )
    return text


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HarnessValidationError(
            f"{field_name} must be non-empty trimmed text",
            code="invalid_graph_definition",
            details={"field": field_name},
        )
    return value


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_definition",
        )
    return value


def _contract_reference(
    value: HarnessContractReference | Mapping[str, Any],
    *,
    expected_kind: HarnessContractKind,
    field: str,
    invalid_code: str = "invalid_graph_leaf_activity_binding",
    kind_mismatch_code: str = "graph_leaf_activity_contract_kind_mismatch",
) -> HarnessContractReference:
    try:
        reference = (
            value
            if isinstance(value, HarnessContractReference)
            else HarnessContractReference.from_dict(_mapping(value, field))
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise HarnessValidationError(
            f"{field} must be an exact Graph contract reference",
            code=invalid_code,
        ) from exc
    if reference.contract_kind is not expected_kind:
        raise HarnessValidationError(
            f"{field} has the wrong Graph contract kind",
            code=kind_mismatch_code,
            details={
                "field": field,
                "expected_kind": expected_kind.value,
                "actual_kind": reference.contract_kind.value,
            },
        )
    return reference


def _exact_reference_text(value: Any, field: str) -> str:
    text = _task_plan_required_text(value, field)
    match = _EXACT_REFERENCE_PATTERN.fullmatch(text)
    if match is None or match.group(2).casefold() in _MOVING_VERSIONS:
        raise HarnessValidationError(
            f"{field} must use exact '<id>@<version>' form",
            code="invalid_graph_task_plan_stage_binding",
            details={"field": field},
        )
    return text


def _exact_schema(value: Any, field: str) -> str:
    text = _task_plan_required_text(value, field)
    if _EXACT_SCHEMA_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field} must use an exact versioned schema",
            code="invalid_graph_task_plan_stage_binding",
            details={"field": field},
        )
    return text


def _unique_text_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field} must be an array",
            code="invalid_graph_task_plan_stage_binding",
            details={"field": field},
        )
    normalized = tuple(_task_plan_required_text(item, field) for item in value)
    if not normalized or len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            f"{field} must contain unique non-empty values",
            code="invalid_graph_task_plan_stage_binding",
            details={"field": field},
        )
    return tuple(sorted(normalized))


def _repair_triggers(value: Any) -> tuple[HarnessGraphRepairTrigger, ...]:
    field = "repair_binding.triggers"
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field} must be an array",
            code="invalid_graph_repair_binding",
            details={"field": field},
        )
    try:
        triggers = tuple(HarnessGraphRepairTrigger(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            f"{field} contains an unsupported trigger",
            code="invalid_graph_repair_binding",
            details={"field": field},
        ) from exc
    if not triggers or len(triggers) != len(set(triggers)):
        raise HarnessValidationError(
            f"{field} must contain unique supported triggers",
            code="invalid_graph_repair_binding",
            details={"field": field},
        )
    return tuple(sorted(triggers, key=lambda item: item.value))


def _task_plan_required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HarnessValidationError(
            f"{field} must be non-empty trimmed text",
            code="invalid_graph_task_plan_stage_binding",
            details={"field": field},
        )
    return value


def _task_plan_support_refs(value: Any) -> Mapping[str, str]:
    field = "task_plan_binding.support_refs"
    if not isinstance(value, Mapping) or set(value) != _TASK_PLAN_SUPPORT_FIELDS:
        actual = set(value) if isinstance(value, Mapping) else set()
        raise HarnessValidationError(
            f"{field} fields are invalid",
            code="invalid_graph_task_plan_stage_binding",
            details={
                "missing": sorted(_TASK_PLAN_SUPPORT_FIELDS.difference(actual)),
                "unexpected": sorted(actual.difference(_TASK_PLAN_SUPPORT_FIELDS)),
            },
        )
    normalized = {
        name: _exact_reference_text(value[name], f"{field}.{name}")
        for name in _TASK_PLAN_SUPPORT_REFERENCE_FIELDS
    }
    normalized["event_schema"] = _exact_schema(
        value["event_schema"],
        f"{field}.event_schema",
    )
    frozen = freeze_json(dict(sorted(normalized.items())), field)
    return cast(Mapping[str, str], frozen)


def _mapping_array(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_definition",
        )
    normalized = tuple(value)
    if any(not isinstance(item, Mapping) for item in normalized):
        raise HarnessValidationError(
            f"{field_name} must contain objects",
            code="invalid_graph_definition",
        )
    return normalized


def _text_array(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_definition",
        )
    return tuple(_required_text(item, field_name) for item in value)


def _exact_mapping(
    value: Any,
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        actual = set(value) if isinstance(value, Mapping) else set()
        raise HarnessValidationError(
            f"{model} fields are invalid",
            code="invalid_graph_definition",
            details={
                "missing": sorted(expected.difference(actual)),
                "unexpected": sorted(actual.difference(expected)),
            },
        )
    return dict(value)


__all__ = [
    "HarnessGraphDefinition",
    "HarnessGraphDefinitionReader",
    "HarnessGraphLeafBinding",
    "HarnessGraphRepairBinding",
    "HarnessGraphRepairTrigger",
    "HarnessGraphTaskPlanStageBinding",
    "MAX_GRAPH_DEFINITION_ACTIVITIES",
]
