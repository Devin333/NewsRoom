from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events import (
    GRAPH_PHASE_TRANSITION_SCHEMA,
    GraphEventContext,
    GraphExecutionPhase,
    GraphPhaseBoundary,
    GraphPhaseTransitionRecord,
    GraphRunIdentity,
)
from framework.events.errors import EventContractError, EventIntegrityError


NOW = datetime(2026, 8, 16, 10, 30, tzinfo=UTC)
CHECKSUM_A = "sha256:" + "a" * 64
CHECKSUM_B = "sha256:" + "b" * 64
CHECKSUM_C = "sha256:" + "c" * 64


def test_graph_phase_transition_round_trips_exact_identity_and_checksum() -> None:
    record = _record(
        phase=GraphExecutionPhase.VERIFY,
        boundary=GraphPhaseBoundary.EXIT,
        gate_evidence_refs=(CHECKSUM_C, CHECKSUM_B),
    )

    payload = record.to_dict()
    restored = GraphPhaseTransitionRecord.from_dict(payload)

    assert restored == record
    assert payload["schema"] == GRAPH_PHASE_TRANSITION_SCHEMA
    assert payload["context"]["graph_id"] == "research.paper-analysis"
    assert payload["context"]["node_id"] == "analyze"
    assert payload["context"]["node_instance_id"] == "analyze:2"
    assert payload["gate_evidence_refs"] == [CHECKSUM_B, CHECKSUM_C]
    restored.verify_integrity()
    restored.assert_envelope_sequence(17)


def test_graph_phase_transition_checksum_is_independent_of_evidence_input_order() -> None:
    forward = _record(gate_evidence_refs=(CHECKSUM_B, CHECKSUM_C))
    reverse = _record(gate_evidence_refs=(CHECKSUM_C, CHECKSUM_B))

    assert forward.to_dict() == reverse.to_dict()
    assert forward.record_checksum == reverse.record_checksum


def test_graph_phase_transition_requires_node_scoped_context() -> None:
    context = GraphEventContext(identity=_identity())

    with pytest.raises(EventContractError, match="requires node identity"):
        _record(context=context)


@pytest.mark.parametrize(
    "field_name",
    ("graph_version", "graph_schema_version", "compiler_version"),
)
def test_graph_phase_transition_rejects_moving_versions(field_name: str) -> None:
    payload = _record().to_dict()
    payload["context"][field_name] = "latest"

    with pytest.raises(EventContractError, match="must be an exact version"):
        GraphPhaseTransitionRecord.from_dict(payload)


def test_graph_phase_transition_rejects_unknown_and_workflow_alias_fields() -> None:
    payload = _record().to_dict()
    payload["workflow_id"] = "legacy-workflow"
    with pytest.raises(EventContractError, match="fields are invalid"):
        GraphPhaseTransitionRecord.from_dict(payload)

    payload = _record().to_dict()
    payload["context"]["workflow_id"] = "legacy-workflow"
    with pytest.raises(EventContractError, match="fields are invalid"):
        GraphPhaseTransitionRecord.from_dict(payload)


def test_graph_phase_transition_rejects_payload_tampering() -> None:
    payload = _record().to_dict()
    payload["attempt"] = 3

    with pytest.raises(EventIntegrityError, match="checksum does not match"):
        GraphPhaseTransitionRecord.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("attempt", -1, "attempt must be a non-negative integer"),
        ("attempt", True, "attempt must be a non-negative integer"),
        ("event_sequence", 0, "event_sequence must be a positive integer"),
        ("phase", "publish", "phase is unsupported"),
        ("boundary", "during", "boundary is unsupported"),
    ),
)
def test_graph_phase_transition_rejects_invalid_lifecycle_fields(
    field_name: str,
    value: object,
    message: str,
) -> None:
    values = {
        "phase": GraphExecutionPhase.PLAN,
        "boundary": GraphPhaseBoundary.ENTRY,
        "attempt": 2,
        "event_sequence": 17,
    }
    values[field_name] = value

    with pytest.raises(EventContractError, match=message):
        _record(**values)


def test_graph_phase_transition_rejects_invalid_schema_and_checksum() -> None:
    payload = _record().to_dict()
    payload["schema"] = "newsroom.harness-graph-phase-transition/v0"
    with pytest.raises(EventContractError, match="schema is unsupported"):
        GraphPhaseTransitionRecord.from_dict(payload)

    payload = _record().to_dict()
    payload["record_checksum"] = CHECKSUM_B
    with pytest.raises(EventIntegrityError, match="checksum does not match"):
        GraphPhaseTransitionRecord.from_dict(payload)


def test_graph_phase_transition_rejects_duplicate_or_noncanonical_evidence() -> None:
    with pytest.raises(EventContractError, match="must be unique"):
        _record(gate_evidence_refs=(CHECKSUM_B, CHECKSUM_B))

    payload = _record(gate_evidence_refs=(CHECKSUM_B, CHECKSUM_C)).to_dict()
    payload["gate_evidence_refs"] = [CHECKSUM_C, CHECKSUM_B]
    with pytest.raises(EventContractError, match="canonical order"):
        GraphPhaseTransitionRecord.from_dict(payload)


def test_graph_phase_transition_rejects_naive_time_and_envelope_mismatch() -> None:
    with pytest.raises(EventContractError, match="timezone-aware"):
        _record(occurred_at=datetime(2026, 8, 16, 10, 30))

    record = _record()
    with pytest.raises(EventContractError, match="differs from durable envelope"):
        record.assert_envelope_sequence(18)


def _identity() -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id="run-phase-contract",
        graph_id="research.paper-analysis",
        graph_version="4",
        graph_schema_version="newsroom.normalized-harness-graph/v3",
        compiler_version="3",
        normalized_graph_checksum=CHECKSUM_A,
    )


def _context() -> GraphEventContext:
    return GraphEventContext(
        identity=_identity(),
        node_id="analyze",
        node_instance_id="analyze:2",
    )


def _record(**overrides: object) -> GraphPhaseTransitionRecord:
    values: dict[str, object] = {
        "context": _context(),
        "phase": GraphExecutionPhase.EXECUTE,
        "boundary": GraphPhaseBoundary.EXIT,
        "attempt": 2,
        "event_sequence": 17,
        "occurred_at": NOW,
    }
    values.update(overrides)
    return GraphPhaseTransitionRecord(**values)
