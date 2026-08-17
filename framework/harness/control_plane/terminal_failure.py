from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphCommitKind,
    HarnessGraphDecisionCommit,
    HarnessGraphProjectionCommit,
)
from framework.harness.control_plane.graph_state import (
    HarnessAttemptEvidenceReference,
    HarnessEvidenceKind,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.graph.canonical import (
    canonical_checksum,
    freeze_json,
    required_text,
    thaw_json,
)
from framework.harness.graph.model import HarnessContractReference
from framework.harness.graph.reference import HarnessGraphReference


HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA = (
    "newsroom.harness-graph-terminal-failure-record/v1"
)

_FAILED_NODE_STATUSES = frozenset(
    {
        HarnessNodeInstanceStatus.FAILED,
        HarnessNodeInstanceStatus.CANCELLED,
        HarnessNodeInstanceStatus.HALTED,
    }
)


@dataclass(frozen=True, slots=True)
class HarnessGraphFailedNodeRecord:
    """Checksum-bound projection of one node implicated by terminal failure."""

    node_id: str
    node_instance_id: str
    status: HarnessNodeInstanceStatus | str
    attempt: int
    replans: int
    node_state_ref: str
    terminal_reason: str | None
    step_ref: HarnessContractReference | None = None
    output_refs: Mapping[str, Any] = field(default_factory=dict)
    gate_evidence: tuple[HarnessAttemptEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        node_id = required_text(self.node_id, "failed_node.node_id")
        node_instance_id = required_text(
            self.node_instance_id,
            "failed_node.node_instance_id",
        )
        status = HarnessNodeInstanceStatus(self.status)
        if status not in _FAILED_NODE_STATUSES:
            raise _failure_error(
                "graph_terminal_failure_node_status_invalid",
                "terminal failure record can contain only failed, cancelled, or halted nodes",
                node_instance_id=node_instance_id,
                status=status.value,
            )
        attempt = _nonnegative_int(self.attempt, "failed_node.attempt")
        replans = _nonnegative_int(self.replans, "failed_node.replans")
        node_state_ref = _checksum(self.node_state_ref, "failed_node.node_state_ref")
        terminal_reason = _optional_text(
            self.terminal_reason,
            "failed_node.terminal_reason",
        )
        if self.step_ref is not None and not isinstance(
            self.step_ref,
            HarnessContractReference,
        ):
            raise TypeError("failed_node.step_ref must be HarnessContractReference")
        output_refs = freeze_json(self.output_refs, "failed_node.output_refs")
        if not isinstance(output_refs, Mapping):
            raise HarnessValidationError(
                "failed node output refs must be an object",
                code="invalid_graph_terminal_failure_record",
            )
        gate_evidence = tuple(self.gate_evidence)
        if not all(
            isinstance(item, HarnessAttemptEvidenceReference)
            for item in gate_evidence
        ):
            raise TypeError(
                "failed_node.gate_evidence must contain HarnessAttemptEvidenceReference values"
            )
        gate_evidence = tuple(
            sorted(
                gate_evidence,
                key=lambda item: (
                    item.event_sequence,
                    item.evidence_ref,
                ),
            )
        )
        identities = tuple(
            (item.evidence_ref, item.attempt, item.event_sequence)
            for item in gate_evidence
        )
        if len(identities) != len(set(identities)):
            raise _failure_error(
                "graph_terminal_failure_gate_evidence_duplicate",
                "terminal failure gate evidence must be unique",
                node_instance_id=node_instance_id,
            )
        for evidence in gate_evidence:
            if (
                evidence.kind is not HarnessEvidenceKind.GATE_RESULT
                or evidence.node_instance_id != node_instance_id
                or evidence.attempt > attempt
            ):
                raise _failure_error(
                    "graph_terminal_failure_gate_evidence_mismatch",
                    "terminal failure gate evidence does not belong to the failed node",
                    node_instance_id=node_instance_id,
                    evidence_ref=evidence.evidence_ref,
                )

        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "replans", replans)
        object.__setattr__(self, "node_state_ref", node_state_ref)
        object.__setattr__(self, "terminal_reason", terminal_reason)
        object.__setattr__(self, "output_refs", output_refs)
        object.__setattr__(self, "gate_evidence", gate_evidence)

    @classmethod
    def from_node(cls, node: HarnessNodeInstanceState) -> Self:
        if not isinstance(node, HarnessNodeInstanceState):
            raise TypeError("node must be HarnessNodeInstanceState")
        return cls(
            node_id=node.identity.node_id,
            node_instance_id=node.instance_id,
            status=node.status,
            attempt=node.attempt,
            replans=node.replans,
            node_state_ref=canonical_checksum(node.to_dict()),
            terminal_reason=node.terminal_reason,
            step_ref=node.step_ref,
            output_refs=thaw_json(node.output_refs),
            gate_evidence=tuple(
                item
                for item in node.evidence_refs
                if item.kind is HarnessEvidenceKind.GATE_RESULT
            ),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "node_id",
                "node_instance_id",
                "status",
                "attempt",
                "replans",
                "node_state_ref",
                "terminal_reason",
                "step_ref",
                "output_refs",
                "gate_evidence",
            },
            "failed node record",
        )
        step_ref = payload["step_ref"]
        return cls(
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            status=payload["status"],
            attempt=payload["attempt"],
            replans=payload["replans"],
            node_state_ref=payload["node_state_ref"],
            terminal_reason=payload["terminal_reason"],
            step_ref=(
                None
                if step_ref is None
                else HarnessContractReference.from_dict(
                    _mapping(step_ref, "failed_node.step_ref")
                )
            ),
            output_refs=_mapping(payload["output_refs"], "failed_node.output_refs"),
            gate_evidence=tuple(
                HarnessAttemptEvidenceReference.from_dict(item)
                for item in _mapping_sequence(
                    payload["gate_evidence"],
                    "failed_node.gate_evidence",
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "status": self.status.value,
            "attempt": self.attempt,
            "replans": self.replans,
            "node_state_ref": self.node_state_ref,
            "terminal_reason": self.terminal_reason,
            "step_ref": None if self.step_ref is None else self.step_ref.to_dict(),
            "output_refs": thaw_json(self.output_refs),
            "gate_evidence": [item.to_dict() for item in self.gate_evidence],
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphTerminalFailureRecord:
    """Canonical evidence that a failed Graph decision was durably projected."""

    run_id: str
    graph_ref: HarnessGraphReference
    terminal_decision_type: HarnessGraphDecisionType | str
    terminal_reason_code: str
    terminal_decision_ref: str
    terminal_decision_commit_ref: str
    terminal_decision_sequence: int
    terminal_projection_ref: str
    terminal_projection_commit_ref: str
    terminal_projection_sequence: int
    decision_evidence_refs: tuple[str, ...]
    failed_nodes: tuple[HarnessGraphFailedNodeRecord, ...]
    schema_version: str = HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA
    record_checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        run_id = required_text(self.run_id, "terminal_failure.run_id")
        if not isinstance(self.graph_ref, HarnessGraphReference):
            raise TypeError("terminal_failure.graph_ref must be HarnessGraphReference")
        terminal_decision_type = HarnessGraphDecisionType(
            self.terminal_decision_type
        )
        if terminal_decision_type not in {
            HarnessGraphDecisionType.COMPLETE_RUN,
            HarnessGraphDecisionType.HALT_RUN,
        }:
            raise _failure_error(
                "graph_terminal_failure_decision_invalid",
                "terminal failure record requires COMPLETE_RUN or HALT_RUN",
                decision_type=terminal_decision_type.value,
            )
        terminal_reason_code = required_text(
            self.terminal_reason_code,
            "terminal_failure.terminal_reason_code",
        )
        terminal_decision_ref = _checksum(
            self.terminal_decision_ref,
            "terminal_failure.terminal_decision_ref",
        )
        terminal_decision_commit_ref = _checksum(
            self.terminal_decision_commit_ref,
            "terminal_failure.terminal_decision_commit_ref",
        )
        terminal_projection_ref = _checksum(
            self.terminal_projection_ref,
            "terminal_failure.terminal_projection_ref",
        )
        terminal_projection_commit_ref = _checksum(
            self.terminal_projection_commit_ref,
            "terminal_failure.terminal_projection_commit_ref",
        )
        terminal_decision_sequence = _positive_int(
            self.terminal_decision_sequence,
            "terminal_failure.terminal_decision_sequence",
        )
        terminal_projection_sequence = _positive_int(
            self.terminal_projection_sequence,
            "terminal_failure.terminal_projection_sequence",
        )
        if terminal_projection_sequence != terminal_decision_sequence + 1:
            raise _failure_error(
                "graph_terminal_failure_sequence_mismatch",
                "terminal failure projection must immediately follow its decision",
            )
        decision_evidence_refs = tuple(
            sorted(
                _checksum(item, "terminal_failure.decision_evidence_refs")
                for item in self.decision_evidence_refs
            )
        )
        if len(decision_evidence_refs) != len(set(decision_evidence_refs)):
            raise _failure_error(
                "graph_terminal_failure_evidence_duplicate",
                "terminal failure decision evidence must be unique",
            )
        failed_nodes = tuple(
            sorted(self.failed_nodes, key=lambda item: item.node_instance_id)
        )
        if not failed_nodes or not all(
            isinstance(item, HarnessGraphFailedNodeRecord) for item in failed_nodes
        ):
            raise _failure_error(
                "graph_terminal_failure_nodes_missing",
                "terminal failure record requires failed node evidence",
            )
        node_ids = tuple(item.node_instance_id for item in failed_nodes)
        node_refs = tuple(item.node_state_ref for item in failed_nodes)
        if len(node_ids) != len(set(node_ids)) or len(node_refs) != len(set(node_refs)):
            raise _failure_error(
                "graph_terminal_failure_nodes_duplicate",
                "terminal failure node evidence must be unique",
            )
        if self.schema_version != HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA:
            raise _failure_error(
                "unsupported_graph_terminal_failure_record_schema",
                "terminal failure record schema is unsupported",
                schema_version=str(self.schema_version),
            )

        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(
            self,
            "terminal_decision_type",
            terminal_decision_type,
        )
        object.__setattr__(self, "terminal_reason_code", terminal_reason_code)
        object.__setattr__(self, "terminal_decision_ref", terminal_decision_ref)
        object.__setattr__(
            self,
            "terminal_decision_commit_ref",
            terminal_decision_commit_ref,
        )
        object.__setattr__(
            self,
            "terminal_decision_sequence",
            terminal_decision_sequence,
        )
        object.__setattr__(self, "terminal_projection_ref", terminal_projection_ref)
        object.__setattr__(
            self,
            "terminal_projection_commit_ref",
            terminal_projection_commit_ref,
        )
        object.__setattr__(
            self,
            "terminal_projection_sequence",
            terminal_projection_sequence,
        )
        object.__setattr__(
            self,
            "decision_evidence_refs",
            decision_evidence_refs,
        )
        object.__setattr__(self, "failed_nodes", failed_nodes)
        expected = canonical_checksum(self.checksum_projection())
        if self.record_checksum is not None and self.record_checksum != expected:
            raise _failure_error(
                "graph_terminal_failure_record_checksum_mismatch",
                "terminal failure record checksum does not match canonical content",
            )
        object.__setattr__(self, "record_checksum", expected)

    @property
    def failed_node_refs(self) -> tuple[str, ...]:
        return tuple(item.node_state_ref for item in self.failed_nodes)

    @property
    def gate_evidence_refs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    evidence.evidence_ref
                    for node in self.failed_nodes
                    for evidence in node.gate_evidence
                }
            )
        )

    @classmethod
    def from_commits(
        cls,
        decision_commit: HarnessGraphDecisionCommit,
        projection_commit: HarnessGraphProjectionCommit,
    ) -> Self:
        if not isinstance(decision_commit, HarnessGraphDecisionCommit):
            raise TypeError("decision_commit must be HarnessGraphDecisionCommit")
        if not isinstance(projection_commit, HarnessGraphProjectionCommit):
            raise TypeError("projection_commit must be HarnessGraphProjectionCommit")
        decision = decision_commit.decision
        state = projection_commit.state
        is_failed_completion = (
            decision.decision_type is HarnessGraphDecisionType.COMPLETE_RUN
            and decision.payload.get("outcome") == RunOutcome.FAILED.value
        )
        is_halt = decision.decision_type is HarnessGraphDecisionType.HALT_RUN
        if (
            not (is_failed_completion or is_halt)
            or decision_commit.side_effect_outcome_ref is not None
        ):
            raise _failure_error(
                "graph_terminal_failure_decision_invalid",
                "terminal failure record requires an unmodified failed COMPLETE_RUN or HALT_RUN decision",
            )
        if (
            projection_commit.commit_kind
            is not HarnessGraphCommitKind.DECISION_PROJECTION
            or projection_commit.cause_checksum != decision.decision_checksum
            or projection_commit.previous_projection_checksum
            != decision.input_projection_checksum
            or projection_commit.sequence != decision_commit.sequence + 1
        ):
            raise _failure_error(
                "graph_terminal_failure_projection_mismatch",
                "terminal failure projection is not the adjacent projection of its decision",
            )
        terminal_state_matches = (
            (
                is_failed_completion
                and state.lifecycle is RunLifecycle.COMPLETED
                and state.outcome is RunOutcome.FAILED
            )
            or (
                is_halt
                and state.lifecycle is RunLifecycle.HALTED
                and state.outcome is not RunOutcome.SUCCEEDED
            )
        )
        if (
            state.run_id != decision.run_id
            or state.graph_ref != decision.graph_ref
            or not terminal_state_matches
            or state.terminal_reason_code != decision.reason_code
            or state.projection_checksum is None
        ):
            raise _failure_error(
                "graph_terminal_failure_state_mismatch",
                "terminal failure state does not match its failed decision",
            )
        failed_nodes = tuple(
            HarnessGraphFailedNodeRecord.from_node(node)
            for node in state.node_instances
            if node.status in _FAILED_NODE_STATUSES
        )
        failed_refs = tuple(sorted(item.node_state_ref for item in failed_nodes))
        if is_failed_completion and failed_refs != tuple(
            sorted(decision.evidence_refs)
        ):
            raise _failure_error(
                "graph_terminal_failure_node_evidence_mismatch",
                "failed decision evidence does not exactly match terminal failed nodes",
                decision_evidence_refs=list(decision.evidence_refs),
                failed_node_refs=list(failed_refs),
            )
        if is_halt:
            failed_node_ids = {
                item.node_instance_id for item in failed_nodes
            }
            if (
                decision.node_instance_id is not None
                and decision.node_instance_id not in failed_node_ids
            ):
                raise _failure_error(
                    "graph_terminal_failure_node_evidence_mismatch",
                    "HALT_RUN does not identify a terminal failed node",
                    node_instance_id=decision.node_instance_id,
                )
        if not set(decision.evidence_refs).issubset(
            decision_commit.accepted_evidence_refs
        ):
            raise _failure_error(
                "graph_terminal_failure_evidence_not_accepted",
                "terminal failure decision references unaccepted node evidence",
            )
        return cls(
            run_id=decision.run_id,
            graph_ref=decision.graph_ref,
            terminal_decision_type=decision.decision_type,
            terminal_reason_code=decision.reason_code,
            terminal_decision_ref=decision.decision_checksum,
            terminal_decision_commit_ref=decision_commit.commit_checksum,
            terminal_decision_sequence=decision_commit.sequence,
            terminal_projection_ref=state.projection_checksum,
            terminal_projection_commit_ref=projection_commit.commit_checksum,
            terminal_projection_sequence=projection_commit.sequence,
            decision_evidence_refs=decision.evidence_refs,
            failed_nodes=failed_nodes,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "run_id",
                "graph_ref",
                "terminal_decision_type",
                "terminal_reason_code",
                "terminal_decision_ref",
                "terminal_decision_commit_ref",
                "terminal_decision_sequence",
                "terminal_projection_ref",
                "terminal_projection_commit_ref",
                "terminal_projection_sequence",
                "decision_evidence_refs",
                "failed_nodes",
                "record_checksum",
            },
            "terminal failure record",
        )
        return cls(
            schema_version=payload["schema_version"],
            run_id=payload["run_id"],
            graph_ref=HarnessGraphReference.from_dict(
                _mapping(payload["graph_ref"], "terminal_failure.graph_ref")
            ),
            terminal_decision_type=payload["terminal_decision_type"],
            terminal_reason_code=payload["terminal_reason_code"],
            terminal_decision_ref=payload["terminal_decision_ref"],
            terminal_decision_commit_ref=payload["terminal_decision_commit_ref"],
            terminal_decision_sequence=payload["terminal_decision_sequence"],
            terminal_projection_ref=payload["terminal_projection_ref"],
            terminal_projection_commit_ref=payload["terminal_projection_commit_ref"],
            terminal_projection_sequence=payload["terminal_projection_sequence"],
            decision_evidence_refs=tuple(payload["decision_evidence_refs"]),
            failed_nodes=tuple(
                HarnessGraphFailedNodeRecord.from_dict(item)
                for item in _mapping_sequence(
                    payload["failed_nodes"],
                    "terminal_failure.failed_nodes",
                )
            ),
            record_checksum=payload["record_checksum"],
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "graph_ref": self.graph_ref.to_dict(),
            "terminal_decision_type": self.terminal_decision_type.value,
            "terminal_reason_code": self.terminal_reason_code,
            "terminal_decision_ref": self.terminal_decision_ref,
            "terminal_decision_commit_ref": self.terminal_decision_commit_ref,
            "terminal_decision_sequence": self.terminal_decision_sequence,
            "terminal_projection_ref": self.terminal_projection_ref,
            "terminal_projection_commit_ref": self.terminal_projection_commit_ref,
            "terminal_projection_sequence": self.terminal_projection_sequence,
            "decision_evidence_refs": list(self.decision_evidence_refs),
            "failed_nodes": [item.to_dict() for item in self.failed_nodes],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}


def _failure_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


def _checksum(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 checksum",
            code="invalid_graph_terminal_failure_record",
        )
    return text


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="invalid_graph_terminal_failure_record",
        )
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessValidationError(
            f"{field_name} must be a non-negative integer",
            code="invalid_graph_terminal_failure_record",
        )
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    return None if value is None else required_text(value, field_name)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_terminal_failure_record",
        )
    return value


def _mapping_sequence(
    value: Any,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_terminal_failure_record",
        )
    items = tuple(value)
    if not all(isinstance(item, Mapping) for item in items):
        raise HarnessValidationError(
            f"{field_name} must contain objects",
            code="invalid_graph_terminal_failure_record",
        )
    return items


def _exact_mapping(
    value: Any,
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        actual = set(value) if isinstance(value, Mapping) else set()
        raise _failure_error(
            "invalid_graph_terminal_failure_record",
            f"{model} fields are invalid",
            missing=sorted(expected.difference(actual)),
            unexpected=sorted(actual.difference(expected)),
        )
    return dict(value)


__all__ = [
    "HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA",
    "HarnessGraphFailedNodeRecord",
    "HarnessGraphTerminalFailureRecord",
]
