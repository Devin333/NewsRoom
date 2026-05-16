from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.framework.workflow.checkpointing import (
    CHECKPOINT_SCHEMA_VERSION,
    envelope_from_checkpoint,
    envelope_to_checkpoint,
)
from storage.checkpoint import WorkflowCheckpoint


def test_checkpoint_envelope_from_checkpoint() -> None:
    checkpoint = _checkpoint()

    envelope = envelope_from_checkpoint(checkpoint, manifest_hash="manifest-sha")

    assert envelope.checkpoint_id == checkpoint.checkpoint_id
    assert envelope.schema_version == CHECKPOINT_SCHEMA_VERSION
    assert envelope.run_id == checkpoint.run_id
    assert envelope.workflow_id == checkpoint.workflow_id
    assert envelope.workflow_version == checkpoint.workflow_version
    assert envelope.current_step_ids == checkpoint.current_step_ids
    assert envelope.data_buffer_snapshot == checkpoint.data_buffer_snapshot
    assert envelope.step_results == checkpoint.step_results
    assert envelope.path == checkpoint.path
    assert envelope.manifest_hash == "manifest-sha"
    assert envelope.metadata["profile"] == "test"
    assert envelope.metadata["event_offset"] == 7


def test_checkpoint_envelope_roundtrip_to_checkpoint() -> None:
    checkpoint = _checkpoint()

    restored = envelope_to_checkpoint(envelope_from_checkpoint(checkpoint))

    assert restored.checkpoint_id == checkpoint.checkpoint_id
    assert restored.run_id == checkpoint.run_id
    assert restored.workflow_id == checkpoint.workflow_id
    assert restored.workflow_version == checkpoint.workflow_version
    assert restored.current_step_ids == checkpoint.current_step_ids
    assert restored.data_buffer_snapshot == checkpoint.data_buffer_snapshot
    assert restored.step_results == checkpoint.step_results
    assert restored.path == checkpoint.path
    assert restored.event_offset == checkpoint.event_offset
    assert restored.created_at == checkpoint.created_at
    assert restored.metadata["profile"] == checkpoint.metadata["profile"]


def test_checkpoint_envelope_requires_schema_version() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())

    with pytest.raises(ValueError, match="schema_version"):
        replace(envelope, schema_version="")


def test_checkpoint_envelope_has_checksum() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())

    assert envelope.checksum
    with pytest.raises(ValueError, match="checksum"):
        replace(envelope, checksum="")


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["write"],
        data_buffer_snapshot={"request": {"topic": "ai"}, "plan": "outline"},
        step_results={"plan": {"status": "succeeded", "outputs": {"plan": "outline"}}},
        path=["plan"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
