from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from framework.events import LegacyEventOffset
from framework.specs import StepSpec, WorkflowSpec
from framework.workflow.checkpoint.checksum import attach_checkpoint_checksum
from framework.workflow.checkpoint.durable import (
    CHECKPOINT_SCHEMA_VERSION_V2,
    DurableWorkflowCheckpoint,
    attach_durable_checkpoint_checksum,
    durable_checkpoint_checksum_payload,
    durable_envelope_from_checkpoint,
    recovery_cursor_from_durable_checkpoint,
    verify_durable_checkpoint_checksum,
)
from framework.workflow.checkpoint.envelope import (
    CHECKPOINT_SCHEMA_VERSION,
    WorkflowCheckpointEnvelope,
    envelope_to_payload,
)
from framework.workflow.checkpoint.migration import (
    LegacyCheckpointBoundaryMapping,
    LegacyCheckpointOffsetSemantics,
    RecordedLegacyCheckpointBoundaryResolver,
    durable_checkpoint_migration_registry,
)
from framework.workflow.checkpoint.store import LocalJsonCheckpointStore


FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "events"
    / "legacy"
    / "valid"
    / "checkpoint_boundary_mappings.json"
)


def test_legacy_and_active_checkpoint_schemas_remain_distinct() -> None:
    assert CHECKPOINT_SCHEMA_VERSION == "workflow-checkpoint/v1"
    assert CHECKPOINT_SCHEMA_VERSION_V2 == "workflow-checkpoint/v2"


@pytest.mark.parametrize(
    ("fixture_name", "expected_after", "next_sequences"),
    [
        ("offset_zero", 1, [2, 3]),
        ("last_line", 3, []),
        ("empty_history", None, [1, 2, 3]),
    ],
)
def test_recorded_legacy_mapping_resumes_exclusively_after_boundary(
    fixture_name: str,
    expected_after: int | None,
    next_sequences: list[int],
) -> None:
    mapping = _mapping(fixture_name)
    envelope = _registry(mapping).migrate_to_v2(
        _legacy_v1_payload(mapping),
        source_semantics=mapping.source_semantics,
    )
    cursor = recovery_cursor_from_durable_checkpoint(
        envelope,
        boundary_event_stream_id=(
            None if expected_after is None else mapping.stream_id
        ),
        boundary_event_sequence=expected_after,
        boundary_event_id=mapping.last_event_id,
    )

    assert cursor.after_sequence == expected_after
    assert [sequence for sequence in (1, 2, 3) if cursor.should_apply(sequence)] == (
        next_sequences
    )
    assert envelope.metadata["legacy_import"] == {
        "mapping_id": mapping.mapping_id,
        "source_schema_version": "workflow-checkpoint/v1",
        "source_semantics": mapping.source_semantics.value,
        "legacy_event_offset": mapping.legacy_event_offset.value,
    }
    assert "event_offset" not in envelope.metadata


def test_same_legacy_offset_has_distinct_meaning_only_via_recorded_mapping() -> None:
    offset_zero = _mapping("offset_zero")
    empty = _mapping("empty_history")

    assert offset_zero.legacy_event_offset == empty.legacy_event_offset
    assert offset_zero.last_durable_stream_sequence == 1
    assert empty.last_durable_stream_sequence is None


def test_nonempty_legacy_checkpoint_without_recorded_mapping_fails_closed() -> None:
    mapping = _mapping("offset_zero")
    empty_resolver = RecordedLegacyCheckpointBoundaryResolver([])

    with pytest.raises(ValueError, match="recorded import mapping"):
        durable_checkpoint_migration_registry(empty_resolver).migrate_to_v2(
            _legacy_v1_payload(mapping),
            source_semantics=mapping.source_semantics,
        )


def test_one_legacy_checkpoint_identity_cannot_select_multiple_offsets() -> None:
    mapping = _mapping("offset_zero")
    alternate = replace(
        mapping,
        mapping_id="mapping-alternate",
        legacy_event_offset=LegacyEventOffset(1),
        last_durable_stream_sequence=2,
        last_event_id="event-sequence-2",
    )

    with pytest.raises(ValueError, match="multiple recorded boundaries"):
        RecordedLegacyCheckpointBoundaryResolver([mapping, alternate])


def test_legacy_metadata_offset_aliases_must_agree() -> None:
    mapping = _mapping("offset_zero")
    payload = _legacy_v1_payload(mapping)
    payload["metadata"]["legacy_event_offset"] = 2
    payload = envelope_to_payload(
        attach_checkpoint_checksum(WorkflowCheckpointEnvelope(**payload))
    )

    with pytest.raises(ValueError, match="conflicting legacy checkpoint event offsets"):
        _registry(mapping).migrate_to_v2(
            payload,
            source_semantics=mapping.source_semantics,
        )


def test_v0_top_level_and_v1_metadata_offsets_conflict_fail_closed() -> None:
    mapping = _mapping("offset_zero")
    payload = _legacy_v1_payload(mapping)
    payload["event_offset"] = 9

    with pytest.raises(ValueError, match="conflicting legacy checkpoint event_offset"):
        _registry(mapping).migrate_to_v2(
            payload,
            source_semantics=mapping.source_semantics,
        )


def test_v0_top_level_offset_migrates_through_v1_to_v2() -> None:
    mapping = _mapping("offset_zero")
    v1 = _legacy_v1_payload(mapping)
    v0 = {
        key: value
        for key, value in v1.items()
        if key not in {"schema_version", "checksum", "manifest_hash", "metadata"}
    }
    v0["event_offset"] = mapping.legacy_event_offset.value
    v0["metadata"] = {}

    migrated = _registry(mapping).migrate_to_v2(
        v0,
        source_semantics=mapping.source_semantics,
    )

    assert migrated.schema_version == CHECKPOINT_SCHEMA_VERSION_V2
    assert [
        item["source_schema_version"] for item in migrated.metadata["migrations"]
    ] == ["workflow-checkpoint/v0", "workflow-checkpoint/v1"]
    assert migrated.last_durable_stream_sequence == 1
    assert migrated.last_event_id == "event-sequence-1"


def test_declared_and_supplied_offset_semantics_conflict_fail_closed() -> None:
    mapping = _mapping("offset_zero")
    payload = _legacy_v1_payload(mapping)
    payload["metadata"]["legacy_offset_semantics"] = (
        LegacyCheckpointOffsetSemantics.RECORDER_EVENT_COUNT.value
    )
    payload = envelope_to_payload(
        attach_checkpoint_checksum(
            WorkflowCheckpointEnvelope(**payload)
        )
    )

    with pytest.raises(ValueError, match="conflicting legacy checkpoint offset semantics"):
        _registry(mapping).migrate_to_v2(
            payload,
            source_semantics=LegacyCheckpointOffsetSemantics.JSONL_LINE_INDEX,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("stream_id", "run:another-run"),
        ("last_durable_stream_sequence", 2),
        ("last_event_id", "another-event"),
    ],
)
def test_v2_checksum_covers_complete_durable_boundary(
    field_name: str,
    replacement: object,
) -> None:
    envelope = durable_envelope_from_checkpoint(_durable_checkpoint())
    changes = {field_name: replacement}
    if field_name == "stream_id":
        changes["run_id"] = "another-run"
    tampered = replace(envelope, **changes)

    assert not verify_durable_checkpoint_checksum(tampered)


def test_v2_rejects_noncanonical_stream_and_unsafe_run_id() -> None:
    checkpoint = _durable_checkpoint()

    with pytest.raises(ValueError, match="authoritative run stream"):
        replace(checkpoint, stream_id="run:other")
    with pytest.raises(ValueError):
        replace(checkpoint, run_id="../escape", stream_id="run:../escape")


def test_recovery_verifies_boundary_event_before_producing_after_sequence() -> None:
    envelope = durable_envelope_from_checkpoint(_durable_checkpoint())

    with pytest.raises(ValueError, match="authoritative stream history"):
        recovery_cursor_from_durable_checkpoint(
            envelope,
            boundary_event_stream_id=envelope.stream_id,
            boundary_event_sequence=envelope.last_durable_stream_sequence,
            boundary_event_id="wrong-event",
        )
    with pytest.raises(ValueError, match="authoritative stream history"):
        recovery_cursor_from_durable_checkpoint(
            envelope,
            boundary_event_stream_id="run:wrong-run",
            boundary_event_sequence=envelope.last_durable_stream_sequence,
            boundary_event_id=envelope.last_event_id,
        )


def test_v2_detaches_mutable_inputs_and_rejects_nondeterministic_json() -> None:
    source_buffer = {"nested": {"items": [1]}}
    source_metadata = {"safe": {"value": "initial"}}
    checkpoint = _durable_checkpoint(
        data_buffer_snapshot=source_buffer,
        metadata=source_metadata,
    )
    envelope = durable_envelope_from_checkpoint(checkpoint)
    before = durable_checkpoint_checksum_payload(envelope)

    source_buffer["nested"]["items"].append(2)
    source_metadata["safe"]["value"] = "changed"

    assert durable_checkpoint_checksum_payload(envelope) == before
    assert verify_durable_checkpoint_checksum(envelope)
    with pytest.raises((TypeError, ValueError)):
        replace(checkpoint, metadata={"bad": object()})


def test_local_store_exposes_explicit_opt_in_import_path(tmp_path: Path) -> None:
    mapping = _mapping("offset_zero")
    store = LocalJsonCheckpointStore(tmp_path)
    run_dir = tmp_path / mapping.run_id
    run_dir.mkdir()
    path = run_dir / f"{mapping.checkpoint_id}.json"
    path.write_text(json.dumps(_legacy_v1_payload(mapping)), encoding="utf-8")

    imported = store.import_durable_checkpoint(
        mapping.run_id,
        mapping.checkpoint_id,
        migration_registry=_registry(mapping),
        source_semantics=mapping.source_semantics,
    )

    assert imported.schema_version == CHECKPOINT_SCHEMA_VERSION_V2
    assert imported.last_durable_stream_sequence == 1
    assert imported.last_event_id == "event-sequence-1"


def _mapping(name: str) -> LegacyCheckpointBoundaryMapping:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))[name]
    raw_offset = payload["legacy_event_offset"]
    return LegacyCheckpointBoundaryMapping(
        mapping_id=payload["mapping_id"],
        checkpoint_id=payload["checkpoint_id"],
        run_id=payload["run_id"],
        source_semantics=payload["source_semantics"],
        legacy_event_offset=(
            None if raw_offset is None else LegacyEventOffset(raw_offset)
        ),
        stream_id=payload["stream_id"],
        last_durable_stream_sequence=payload["last_durable_stream_sequence"],
        last_event_id=payload["last_event_id"],
    )


def _registry(mapping: LegacyCheckpointBoundaryMapping):
    resolver = RecordedLegacyCheckpointBoundaryResolver([mapping])
    return durable_checkpoint_migration_registry(resolver)


def _legacy_v1_payload(mapping: LegacyCheckpointBoundaryMapping) -> dict:
    envelope = WorkflowCheckpointEnvelope(
        checkpoint_id=mapping.checkpoint_id,
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        run_id=mapping.run_id,
        workflow_id="workflow-checkpoint-migration",
        workflow_version="1.0",
        current_step_ids=[],
        data_buffer_snapshot={"applied": True},
        step_results={},
        path=[],
        manifest_hash=None,
        checksum="pending",
        created_at="2026-07-15T00:00:00Z",
        metadata={"event_offset": mapping.legacy_event_offset.value},
    )
    return envelope_to_payload(attach_checkpoint_checksum(envelope))


def _durable_checkpoint(**overrides: object) -> DurableWorkflowCheckpoint:
    values = {
        "checkpoint_id": "cp-durable",
        "run_id": "run-durable",
        "workflow_id": "workflow-durable",
        "workflow_version": "2.0",
        "current_step_ids": [],
        "data_buffer_snapshot": {"state": "accepted"},
        "stream_id": "run:run-durable",
        "last_durable_stream_sequence": 1,
        "last_event_id": "event-1",
        "created_at": datetime(2026, 7, 15, tzinfo=UTC),
        "metadata": {},
    }
    values.update(overrides)
    return DurableWorkflowCheckpoint(**values)
