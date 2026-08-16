from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import HarnessGraphReference
from framework.harness.graph.canonical import (
    canonical_checksum,
    exact_reference,
    freeze_json,
    required_text,
    thaw_json,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_GRAPH_CONTROL_POLICY_VERSION,
    HARNESS_GRAPH_DECISION_SCHEMA,
    HARNESS_GRAPH_EVALUATOR_VERSION,
    HARNESS_STEP_LIFECYCLE_VERSION,
)


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class HarnessGraphDecisionType(StrEnum):
    ACTIVATE_NODE = "activate_node"
    ENTER_STEP_PHASE = "enter_step_phase"
    DISPATCH_ACTIVITY = "dispatch_activity"
    VERIFY_ACTIVITY_RESULT = "verify_activity_result"
    PREPARE_SIDE_EFFECT = "prepare_side_effect"
    COMPLETE_NODE = "complete_node"
    COMPLETE_CONTROL_NODE = "complete_control_node"
    FAIL_NODE = "fail_node"
    RETRY_NODE = "retry_node"
    REPLAN_NODE = "replan_node"
    ROUTE_TO_REPAIR = "route_to_repair"
    WAIT_NODE = "wait_node"
    OPEN_FORK = "open_fork"
    SELECT_CHOICE = "select_choice"
    SATISFY_JOIN = "satisfy_join"
    FAIL_JOIN = "fail_join"
    START_LOOP_ITERATION = "start_loop_iteration"
    EXIT_LOOP = "exit_loop"
    EXHAUST_LOOP = "exhaust_loop"
    REGISTER_WAIT = "register_wait"
    RESUME_WAIT = "resume_wait"
    APPLY_MERGE = "apply_merge"
    SELECT_PARALLEL_WINNER = "select_parallel_winner"
    REQUEST_BRANCH_CANCEL = "request_branch_cancel"
    SCHEDULE_COMPENSATION = "schedule_compensation"
    PROJECT_RUN_WAITING = "project_run_waiting"
    COMPLETE_RUN = "complete_run"
    HALT_RUN = "halt_run"


_STEP_DECISION_TYPES = frozenset(
    {
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        HarnessGraphDecisionType.COMPLETE_NODE,
        HarnessGraphDecisionType.FAIL_NODE,
        HarnessGraphDecisionType.RETRY_NODE,
        HarnessGraphDecisionType.REPLAN_NODE,
        HarnessGraphDecisionType.ROUTE_TO_REPAIR,
        HarnessGraphDecisionType.WAIT_NODE,
    }
)
_NODE_INSTANCE_DECISION_TYPES = frozenset(
    {
        *_STEP_DECISION_TYPES,
        HarnessGraphDecisionType.OPEN_FORK,
        HarnessGraphDecisionType.COMPLETE_CONTROL_NODE,
        HarnessGraphDecisionType.SELECT_CHOICE,
        HarnessGraphDecisionType.SATISFY_JOIN,
        HarnessGraphDecisionType.FAIL_JOIN,
        HarnessGraphDecisionType.START_LOOP_ITERATION,
        HarnessGraphDecisionType.EXIT_LOOP,
        HarnessGraphDecisionType.EXHAUST_LOOP,
        HarnessGraphDecisionType.REGISTER_WAIT,
        HarnessGraphDecisionType.RESUME_WAIT,
        HarnessGraphDecisionType.APPLY_MERGE,
        HarnessGraphDecisionType.SELECT_PARALLEL_WINNER,
        HarnessGraphDecisionType.REQUEST_BRANCH_CANCEL,
    }
)
_NODE_DEFINITION_DECISION_TYPES = frozenset(
    {
        HarnessGraphDecisionType.ACTIVATE_NODE,
        HarnessGraphDecisionType.SCHEDULE_COMPENSATION,
    }
)
_REQUIRED_STEP_BINDINGS = frozenset({"step", "worker", "activity"})
_REQUIRED_COMPENSATION_BINDINGS = frozenset({"compensation", "activity"})
_OPTIONAL_STEP_IDENTITY_DECISION_TYPES = frozenset({HarnessGraphDecisionType.HALT_RUN})


@dataclass(frozen=True, slots=True)
class HarnessGraphDecision:
    decision_type: HarnessGraphDecisionType | str
    run_id: str
    graph_ref: HarnessGraphReference
    input_projection_checksum: str
    observation_checksum: str
    reason_code: str
    node_id: str | None = None
    node_instance_id: str | None = None
    step_ref: HarnessContractReference | None = None
    attempt: int | None = None
    target_node_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    binding_versions: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str | None = None
    scheduler_version: str = HARNESS_GRAPH_CONTROL_POLICY_VERSION
    evaluator_version: str = HARNESS_GRAPH_EVALUATOR_VERSION
    step_lifecycle_version: str = HARNESS_STEP_LIFECYCLE_VERSION
    decision_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        decision_type = HarnessGraphDecisionType(self.decision_type)
        run_id = required_text(self.run_id, "graph_decision.run_id")
        if not isinstance(self.graph_ref, HarnessGraphReference):
            raise TypeError("graph_ref must be HarnessGraphReference")
        input_checksum = _checksum(
            self.input_projection_checksum,
            "graph_decision.input_projection_checksum",
        )
        observation_checksum = _checksum(
            self.observation_checksum,
            "graph_decision.observation_checksum",
        )
        reason_code = required_text(
            self.reason_code,
            "graph_decision.reason_code",
        )
        node_id = _optional_text(self.node_id, "graph_decision.node_id")
        node_instance_id = _optional_text(
            self.node_instance_id,
            "graph_decision.node_instance_id",
        )
        if self.step_ref is not None:
            if not isinstance(self.step_ref, HarnessContractReference):
                raise TypeError("step_ref must be HarnessContractReference")
            if self.step_ref.contract_kind is not HarnessContractKind.STEP:
                raise HarnessValidationError(
                    "graph Step decision requires an exact Step contract reference",
                    code="graph_decision_step_reference_mismatch",
                )
        attempt = self.attempt
        if attempt is not None and (
            not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0
        ):
            raise HarnessValidationError(
                "graph decision attempt must be a non-negative integer",
                code="invalid_graph_decision_attempt",
            )
        targets = _ordered_unique_text_tuple(
            self.target_node_ids,
            "graph_decision.target_node_ids",
        )
        evidence_refs = tuple(
            sorted(
                _checksum(item, "graph_decision.evidence_refs")
                for item in self.evidence_refs
            )
        )
        if len(evidence_refs) != len(set(evidence_refs)):
            raise HarnessValidationError(
                "graph decision evidence references must be unique",
                code="duplicate_graph_decision_evidence",
            )
        versions = _freeze_versions(self.binding_versions)
        payload = freeze_json(self.payload, "graph_decision.payload")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "graph decision payload must be an object",
                code="invalid_graph_decision_payload",
            )
        _validate_decision_identity(
            decision_type,
            node_id=node_id,
            node_instance_id=node_instance_id,
            step_ref=self.step_ref,
            attempt=attempt,
            binding_versions=versions,
        )
        expected_schema = (
            GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA
            if self.graph_ref.schema_version
            == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
            else HARNESS_GRAPH_DECISION_SCHEMA
        )
        schema_version = (
            expected_schema if self.schema_version is None else self.schema_version
        )
        if schema_version not in {
            HARNESS_GRAPH_DECISION_SCHEMA,
            GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA,
        }:
            raise HarnessValidationError(
                "unsupported graph decision schema",
                code="unsupported_graph_decision_schema",
            )
        if schema_version != expected_schema:
            raise HarnessValidationError(
                "graph decision schema does not match its normalized Graph reference",
                code="graph_decision_schema_mismatch",
            )
        if (
            schema_version == GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA
            and decision_type is HarnessGraphDecisionType.COMPLETE_RUN
            and payload.get("outcome", "succeeded") == "succeeded"
        ):
            if not evidence_refs:
                raise HarnessValidationError(
                    "Graph-only successful completion requires terminal evidence",
                    code="graph_terminal_evidence_missing",
                )
            if not isinstance(versions.get("terminal_policy"), str):
                raise HarnessValidationError(
                    "Graph-only successful completion requires a pinned terminal policy",
                    code="graph_terminal_policy_version_missing",
                )
        if self.scheduler_version != HARNESS_GRAPH_CONTROL_POLICY_VERSION:
            raise HarnessValidationError(
                "unsupported graph scheduler policy version",
                code="unsupported_graph_scheduler_version",
            )
        if self.evaluator_version != HARNESS_GRAPH_EVALUATOR_VERSION:
            raise HarnessValidationError(
                "unsupported graph evaluator version",
                code="unsupported_graph_evaluator_version",
            )
        if self.step_lifecycle_version != HARNESS_STEP_LIFECYCLE_VERSION:
            raise HarnessValidationError(
                "unsupported Step lifecycle version",
                code="unsupported_step_lifecycle_version",
            )
        object.__setattr__(self, "decision_type", decision_type)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "input_projection_checksum", input_checksum)
        object.__setattr__(self, "observation_checksum", observation_checksum)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "target_node_ids", targets)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "binding_versions", versions)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(
            self,
            "decision_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scheduler_version": self.scheduler_version,
            "evaluator_version": self.evaluator_version,
            "step_lifecycle_version": self.step_lifecycle_version,
            "decision_type": self.decision_type.value,
            "run_id": self.run_id,
            "graph_ref": self.graph_ref.to_dict(),
            "input_projection_checksum": self.input_projection_checksum,
            "observation_checksum": self.observation_checksum,
            "reason_code": self.reason_code,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "step_ref": None if self.step_ref is None else self.step_ref.to_dict(),
            "attempt": self.attempt,
            "target_node_ids": list(self.target_node_ids),
            "evidence_refs": list(self.evidence_refs),
            "binding_versions": thaw_json(self.binding_versions),
            "payload": thaw_json(self.payload),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "decision_checksum": self.decision_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessGraphDecision":
        _exact_keys(
            value,
            {
                "schema_version",
                "scheduler_version",
                "evaluator_version",
                "step_lifecycle_version",
                "decision_type",
                "run_id",
                "graph_ref",
                "input_projection_checksum",
                "observation_checksum",
                "reason_code",
                "node_id",
                "node_instance_id",
                "step_ref",
                "attempt",
                "target_node_ids",
                "evidence_refs",
                "binding_versions",
                "payload",
                "decision_checksum",
            },
            "graph decision",
        )
        decision = cls(
            schema_version=value["schema_version"],
            scheduler_version=value["scheduler_version"],
            evaluator_version=value["evaluator_version"],
            step_lifecycle_version=value["step_lifecycle_version"],
            decision_type=value["decision_type"],
            run_id=value["run_id"],
            graph_ref=HarnessGraphReference.from_dict(value["graph_ref"]),
            input_projection_checksum=value["input_projection_checksum"],
            observation_checksum=value["observation_checksum"],
            reason_code=value["reason_code"],
            node_id=value["node_id"],
            node_instance_id=value["node_instance_id"],
            step_ref=(
                None
                if value["step_ref"] is None
                else HarnessContractReference.from_dict(value["step_ref"])
            ),
            attempt=value["attempt"],
            target_node_ids=tuple(
                _array(value["target_node_ids"], "graph_decision.target_node_ids")
            ),
            evidence_refs=tuple(
                _array(value["evidence_refs"], "graph_decision.evidence_refs")
            ),
            binding_versions=value["binding_versions"],
            payload=value["payload"],
        )
        if value["decision_checksum"] != decision.decision_checksum:
            raise HarnessValidationError(
                "graph decision checksum does not match canonical content",
                code="graph_decision_checksum_mismatch",
                details={
                    "expected": decision.decision_checksum,
                    "actual": str(value["decision_checksum"]),
                },
            )
        return decision


def _validate_decision_identity(
    decision_type: HarnessGraphDecisionType,
    *,
    node_id: str | None,
    node_instance_id: str | None,
    step_ref: HarnessContractReference | None,
    attempt: int | None,
    binding_versions: Mapping[str, Any],
) -> None:
    if decision_type is HarnessGraphDecisionType.PREPARE_SIDE_EFFECT:
        terminal_scope = (
            node_id is None
            and node_instance_id is None
            and step_ref is None
            and attempt is None
        )
        node_scope = (
            node_id is not None
            and node_instance_id is not None
            and step_ref is not None
            and attempt is not None
        )
        if not terminal_scope and not node_scope:
            raise HarnessValidationError(
                "side-effect preparation requires either complete node identity or run scope",
                code="graph_decision_identity_mismatch",
            )
        if node_scope:
            assert step_ref is not None
            _validate_step_bindings(step_ref, binding_versions)
        return
    if decision_type in _NODE_DEFINITION_DECISION_TYPES:
        if node_id is None or node_instance_id is not None:
            raise HarnessValidationError(
                "node scheduling requires definition identity before instance allocation",
                code="graph_decision_identity_mismatch",
            )
    elif decision_type in _NODE_INSTANCE_DECISION_TYPES:
        if node_id is None or node_instance_id is None:
            raise HarnessValidationError(
                "node decision requires definition and instance identity",
                code="graph_decision_identity_mismatch",
            )
    has_step_identity = step_ref is not None or attempt is not None
    if decision_type in _STEP_DECISION_TYPES:
        if step_ref is None or attempt is None:
            raise HarnessValidationError(
                "Step decision requires exact Step reference and attempt identity",
                code="graph_decision_step_identity_missing",
            )
        if decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY and attempt < 1:
            raise HarnessValidationError(
                "Activity dispatch requires a positive target attempt",
                code="invalid_graph_decision_attempt",
            )
        _validate_step_bindings(step_ref, binding_versions)
    elif decision_type in _OPTIONAL_STEP_IDENTITY_DECISION_TYPES and has_step_identity:
        if (
            node_id is None
            or node_instance_id is None
            or step_ref is None
            or attempt is None
        ):
            raise HarnessValidationError(
                "Step-triggered run halt requires complete node and Step identity",
                code="graph_decision_step_identity_missing",
            )
        _validate_step_bindings(step_ref, binding_versions)
    elif has_step_identity:
        raise HarnessValidationError(
            "graph control decision cannot carry Step attempt identity",
            code="graph_decision_identity_mismatch",
        )
    if decision_type is HarnessGraphDecisionType.SCHEDULE_COMPENSATION:
        missing_bindings = _REQUIRED_COMPENSATION_BINDINGS.difference(binding_versions)
        if missing_bindings:
            raise HarnessValidationError(
                "compensation decision is missing exact runtime bindings",
                code="graph_decision_binding_missing",
                details={"missing": sorted(missing_bindings)},
            )
    if node_instance_id is not None and node_id is None:
        raise HarnessValidationError(
            "node instance identity requires its definition identity",
            code="graph_decision_identity_mismatch",
        )


def _validate_step_bindings(
    step_ref: HarnessContractReference,
    binding_versions: Mapping[str, Any],
) -> None:
    missing_bindings = _REQUIRED_STEP_BINDINGS.difference(binding_versions)
    if missing_bindings:
        raise HarnessValidationError(
            "Step decision is missing exact runtime bindings",
            code="graph_decision_binding_missing",
            details={"missing": sorted(missing_bindings)},
        )
    if binding_versions["step"] != step_ref.exact_ref:
        raise HarnessValidationError(
            "Step decision binding does not match step_ref",
            code="graph_decision_binding_mismatch",
        )


def _freeze_versions(value: Any) -> Mapping[str, Any]:
    frozen = freeze_json(value, "graph_decision.binding_versions")
    if not isinstance(frozen, Mapping):
        raise HarnessValidationError(
            "graph decision binding versions must be an object",
            code="invalid_graph_decision_versions",
        )
    normalized: dict[str, str] = {}
    for name, version in frozen.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise HarnessValidationError(
                "graph decision binding names must be canonical non-blank strings",
                code="invalid_graph_decision_versions",
            )
        if not isinstance(version, str):
            raise HarnessValidationError(
                "graph decision binding versions must be exact references",
                code="invalid_graph_decision_versions",
            )
        try:
            exact_version = exact_reference(
                version,
                f"graph_decision.binding_versions.{name}",
            )
        except HarnessValidationError as exc:
            raise HarnessValidationError(
                "graph decision cannot pin an inexact runtime binding",
                code="graph_decision_inexact_version",
                details={"binding": name, "version": version},
            ) from exc
        if exact_version != version:
            raise HarnessValidationError(
                "graph decision runtime binding must already be canonical",
                code="graph_decision_inexact_version",
                details={"binding": name, "version": version},
            )
        normalized[name] = exact_version
    return freeze_json(normalized, "graph_decision.binding_versions")


def _ordered_unique_text_tuple(
    values: Sequence[Any],
    field_name: str,
) -> tuple[str, ...]:
    normalized = tuple(required_text(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            f"{field_name} must not contain duplicates",
            code="duplicate_graph_decision_identity",
        )
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    return None if value is None else required_text(value, field_name)


def _checksum(value: Any, field_name: str) -> str:
    normalized = required_text(value, field_name)
    if _CHECKSUM_PATTERN.fullmatch(normalized) is None:
        raise HarnessValidationError(
            f"{field_name} must be a canonical sha256 reference",
            code="invalid_graph_decision_checksum_reference",
        )
    return normalized


def _array(value: Any, field_name: str) -> list[Any] | tuple[Any, ...]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_decision_projection",
        )
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_decision_projection",
        )
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} fields do not match its schema",
            code="invalid_graph_decision_projection",
            details={
                "missing": sorted(expected.difference(actual)),
                "unknown": sorted(str(item) for item in actual.difference(expected)),
            },
        )


__all__ = [
    "HarnessGraphDecision",
    "HarnessGraphDecisionType",
]
