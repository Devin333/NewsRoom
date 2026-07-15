from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    PayloadReference,
    ProducerIdentity,
    StoredEvent,
    TraceBlock,
    assert_same_event_identity,
    normalize_canonical_json,
)
from framework.events.errors import (
    EventCanonicalizationError,
    EventExtensionLimitError,
    EventIdentityCollisionError,
    EventIntegrityError,
    EventPayloadTooLargeError,
)
from framework.events.schema import SecurityClassification


OCCURRED_AT = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 15, 1, 0, 1, tzinfo=UTC)


def _candidate(**overrides: object) -> EventCandidate:
    values: dict[str, object] = {
        "event_id": "evt-canonical-1",
        "event_type": "workflow_started",
        "data_schema": "newsroom.workflow-event/v1",
        "source": "framework.workflow",
        "occurred_at": OCCURRED_AT,
        "stream_id": "run:run-1",
        "business_context": BusinessContext(run_id="run-1", workflow_id="wf-1"),
        "producer": ProducerIdentity(component="workflow-runtime", version="1"),
        "trace": TraceBlock(
            trace_id="1" * 32,
            span_id="2" * 16,
            trace_flags="01",
        ),
        "tenant_id": "tenant-1",
        "security_classification": SecurityClassification.INTERNAL,
        "payload": {"nested": {"items": [1, {"safe": True}]}},
        "extensions": {"io.newsroom.test": "value"},
    }
    values.update(overrides)
    return EventCandidate(**values)


def test_candidate_and_stored_event_are_deeply_immutable_snapshots() -> None:
    source = {"nested": {"items": [1, {"safe": True}]}}
    candidate = _candidate(payload=source)
    stored = StoredEvent(candidate, observed_at=OBSERVED_AT, stream_sequence=1)
    before = stored.to_dict()

    source["nested"]["items"][1]["safe"] = False
    source["nested"]["items"].append(3)
    with pytest.raises(TypeError):
        stored.payload["nested"]["items"][1]["safe"] = False  # type: ignore[index]

    assert stored.to_dict() == before
    assert stored.payload == {"nested": {"items": (1, {"safe": True})}}


@pytest.mark.parametrize("value", [object(), b"bytes", float("nan"), float("inf")])
def test_canonical_json_rejects_unsupported_or_non_finite_values(value: object) -> None:
    with pytest.raises(EventCanonicalizationError):
        normalize_canonical_json({"value": value})


def test_payload_and_extension_limits_are_enforced() -> None:
    with pytest.raises(EventPayloadTooLargeError):
        _candidate(payload={"body": "x" * 128}, max_inline_payload_bytes=32)
    with pytest.raises(EventExtensionLimitError):
        _candidate(extensions={"a": 1, "b": 2}, max_extension_count=1)
    with pytest.raises(EventExtensionLimitError):
        _candidate(extensions={"a": "x" * 128}, max_extension_bytes=32)


def test_content_and_record_checksums_round_trip_and_detect_tampering() -> None:
    stored = StoredEvent(_candidate(), observed_at=OBSERVED_AT, stream_sequence=7)
    restored = StoredEvent.from_dict(stored.to_dict())

    assert restored.to_dict() == stored.to_dict()
    assert restored.content_checksum.startswith("sha256:")
    assert restored.record_checksum.startswith("sha256:")

    tampered_payload = stored.to_dict()
    tampered_payload["payload"]["nested"]["items"].append("tampered")
    with pytest.raises(EventIntegrityError):
        StoredEvent.from_dict(tampered_payload)

    tampered_sequence = stored.to_dict()
    tampered_sequence["stream_sequence"] = 8
    with pytest.raises(EventIntegrityError):
        StoredEvent.from_dict(tampered_sequence)


@pytest.mark.parametrize(
    ("container", "field_name"),
    [
        ("top", "forged_admin_scope"),
        ("business_context", "forged_run_scope"),
        ("producer", "forged_instance_scope"),
    ],
)
def test_canonical_reader_rejects_unknown_unchecksummed_fields(
    container: str,
    field_name: str,
) -> None:
    payload = StoredEvent(
        _candidate(),
        observed_at=OBSERVED_AT,
        stream_sequence=1,
    ).to_dict()
    if container == "top":
        payload[field_name] = "tenant-b"
    else:
        payload[container][field_name] = "tenant-b"

    with pytest.raises(EventCanonicalizationError):
        StoredEvent.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stream_id", "run:run-2"),
        ("tenant_id", "tenant-2"),
        ("data_schema", "newsroom.workflow-event/v2"),
        ("security_classification", SecurityClassification.PUBLIC),
        ("business_context", BusinessContext(run_id="run-2")),
        (
            "producer",
            ProducerIdentity(component="different-producer", version="1"),
        ),
    ],
)
def test_same_id_boundary_changes_produce_identity_collision(
    field: str,
    value: object,
) -> None:
    existing = StoredEvent(_candidate(), observed_at=OBSERVED_AT, stream_sequence=1)
    changed = _candidate(**{field: value})

    assert changed.content_checksum != existing.content_checksum
    with pytest.raises(EventIdentityCollisionError):
        assert_same_event_identity(existing, changed)


def test_payload_reference_is_in_content_identity() -> None:
    reference_a = PayloadReference(
        uri="artifact://run-1/a.json",
        expected_checksum="sha256:" + "a" * 64,
    )
    reference_b = PayloadReference(
        uri="artifact://run-1/b.json",
        expected_checksum="sha256:" + "b" * 64,
    )
    existing = StoredEvent(
        _candidate(payload=None, payload_ref=reference_a),
        observed_at=OBSERVED_AT,
        stream_sequence=1,
    )
    changed = _candidate(payload=None, payload_ref=reference_b)

    with pytest.raises(EventIdentityCollisionError):
        assert_same_event_identity(existing, changed)


def test_identical_uncertain_commit_candidate_matches_existing_event() -> None:
    candidate = _candidate()
    existing = StoredEvent(candidate, observed_at=OBSERVED_AT, stream_sequence=3)

    assert_same_event_identity(existing, _candidate())
    assert existing.stream_sequence == 3
    assert existing.observed_at == OBSERVED_AT


def test_occurrence_and_observation_time_are_independent_and_utc() -> None:
    stored = StoredEvent(_candidate(), observed_at=OBSERVED_AT, stream_sequence=1)

    assert stored.occurred_at == OCCURRED_AT
    assert stored.observed_at == OBSERVED_AT
    assert stored.to_dict()["occurred_at"] == "2026-07-15T01:00:00Z"
    assert stored.to_dict()["observed_at"] == "2026-07-15T01:00:01Z"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", 123),
        ("stream_id", object()),
        ("business_context", []),
    ],
)
def test_candidate_rejects_silent_core_field_type_coercion(
    field: str,
    value: object,
) -> None:
    with pytest.raises(EventCanonicalizationError):
        _candidate(**{field: value})


def test_trace_and_payload_reference_reject_silent_scalar_coercion() -> None:
    with pytest.raises(EventCanonicalizationError):
        TraceBlock(trace_id="1" * 32, span_id="2" * 16, is_remote="false")  # type: ignore[arg-type]
    with pytest.raises(EventCanonicalizationError):
        PayloadReference(
            uri="artifact://run-1/payload.json",
            expected_checksum="sha256:" + "a" * 64,
            size_bytes="12",  # type: ignore[arg-type]
        )


def test_canonical_reader_requires_explicit_security_and_content_type() -> None:
    payload = StoredEvent(
        _candidate(),
        observed_at=OBSERVED_AT,
        stream_sequence=1,
    ).to_dict()

    for field in ("security_classification", "content_type", "business_context"):
        incomplete = dict(payload)
        incomplete.pop(field)
        with pytest.raises((EventCanonicalizationError, ValueError)):
            StoredEvent.from_dict(incomplete)


def test_canonical_reader_requires_explicit_nested_trace_and_reference_fields() -> None:
    traced = StoredEvent(
        _candidate(),
        observed_at=OBSERVED_AT,
        stream_sequence=1,
    ).to_dict()
    for field in ("trace_flags", "is_remote"):
        incomplete = dict(traced)
        incomplete["trace"] = dict(traced["trace"])
        incomplete["trace"].pop(field)
        with pytest.raises((EventCanonicalizationError, ValueError)):
            StoredEvent.from_dict(incomplete, verify_checksum=False)

    referenced = StoredEvent(
        _candidate(
            payload=None,
            payload_ref=PayloadReference(
                uri="artifact://run-1/payload.json",
                expected_checksum="sha256:" + "a" * 64,
            ),
        ),
        observed_at=OBSERVED_AT,
        stream_sequence=1,
    ).to_dict()
    incomplete_reference = dict(referenced)
    incomplete_reference["payload_ref"] = dict(referenced["payload_ref"])
    incomplete_reference["payload_ref"].pop("content_type")
    with pytest.raises((EventCanonicalizationError, ValueError)):
        StoredEvent.from_dict(incomplete_reference, verify_checksum=False)


@pytest.mark.parametrize("sequence", [True, "1", 1.0])
def test_stored_event_rejects_non_integer_sequence(sequence: object) -> None:
    with pytest.raises(EventCanonicalizationError):
        StoredEvent(_candidate(), observed_at=OBSERVED_AT, stream_sequence=sequence)  # type: ignore[arg-type]
