from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import pytest

import framework.workflow.checkpoint.store as checkpoint_store_module
from framework.agent.artifacts import ArtifactManager
from framework.events import EventRuntime, default_event_schema_catalog
from framework.specs import StepSpec, WorkflowSpec
from framework.workflow.checkpoint.durable import (
    CHECKPOINT_SCHEMA_VERSION_V2,
    DurableWorkflowCheckpoint,
    durable_envelope_from_checkpoint,
)
from framework.workflow.checkpoint.recovery import verified_checkpoint_recovery_cursor
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.checkpoint.store import LocalJsonCheckpointStore
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import (
    WorkflowExecutionContext,
    build_execution_context,
)
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.registry import StepRunnerRegistry
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _NoListRecorder:
    def __init__(self, recorder: Any) -> None:
        self._recorder = recorder

    @property
    def last_accepted_event(self):
        return self._recorder.last_accepted_event

    def emit(self, *args: Any, **kwargs: Any):
        return self._recorder.emit(*args, **kwargs)

    def list_events(self) -> None:
        raise AssertionError("checkpoint writer must not count compatibility events")


class _RecordingStore:
    def __init__(self, event_store: SQLiteEventStore, stream_id: str) -> None:
        self._event_store = event_store
        self._stream_id = stream_id
        self.saved: list[DurableWorkflowCheckpoint] = []
        self.high_watermarks_at_save: list[int | None] = []

    def save_checkpoint(self, checkpoint: DurableWorkflowCheckpoint) -> None:
        self.high_watermarks_at_save.append(
            self._event_store.get_stream_high_watermark(self._stream_id)
        )
        self.saved.append(checkpoint)


class _FailingStore:
    def save_checkpoint(self, checkpoint: DurableWorkflowCheckpoint) -> None:
        raise OSError("checkpoint storage unavailable")


def test_active_writer_uses_last_accepted_durable_event_and_emits_after_save(
    tmp_path: Path,
) -> None:
    context, event_store = _context(tmp_path, run_id="run-checkpoint-boundary")
    accepted = context.recorder.emit(
        "workflow_started",
        {"workflow_version": context.workflow.version, "profile": context.profile},
        trace_context=context.trace_context,
    )
    context.path.append("s1")
    context.step_results["s1"] = StepOutcome.success("s1", {"ok": True})
    store = _RecordingStore(event_store, context.event_emitter.stream_id)

    checkpoint_id = CheckpointCoordinator(checkpoint_store=store).write_checkpoint(
        run_id=context.run_id,
        workflow=context.workflow,
        profile=context.profile,
        current_step_ids=[],
        buffer=context.buffer,
        step_results=context.step_results,
        path=context.path,
        recorder=_NoListRecorder(context.recorder),
        manifest=context.manifest,
        checkpoint_ids=context.checkpoint_ids,
        trace_context=context.trace_context,
    )

    checkpoint = store.saved[0]
    reference_metadata = context.manifest["checkpoint_refs"][0]["metadata"]
    durable_events = context.event_emitter.list_events()
    assert checkpoint_id == "cp-000001-s1"
    assert checkpoint.last_durable_stream_sequence == accepted.sequence == 1
    assert checkpoint.last_event_id == accepted.event_id
    assert store.high_watermarks_at_save == [1]
    assert [event.event_type for event in durable_events] == [
        "workflow_started",
        "checkpoint_created",
    ]
    assert reference_metadata == {
        "stream_id": "run:run-checkpoint-boundary",
        "last_durable_stream_sequence": 1,
        "last_event_id": accepted.event_id,
        "profile": "test",
        "current_step_ids": [],
        "path": ["s1"],
    }
    assert "event_offset" not in reference_metadata


def test_active_writer_represents_an_empty_stream_with_an_empty_boundary(
    tmp_path: Path,
) -> None:
    context, event_store = _context(tmp_path, run_id="run-empty-boundary")
    store = _RecordingStore(event_store, context.event_emitter.stream_id)

    checkpoint_id = CheckpointCoordinator(checkpoint_store=store).write_checkpoint(
        run_id=context.run_id,
        workflow=context.workflow,
        profile=context.profile,
        current_step_ids=["s1"],
        buffer=context.buffer,
        step_results=context.step_results,
        path=context.path,
        recorder=_NoListRecorder(context.recorder),
        manifest=context.manifest,
        checkpoint_ids=context.checkpoint_ids,
        trace_context=context.trace_context,
    )

    checkpoint = store.saved[0]
    assert checkpoint_id == "cp-000000-start"
    assert checkpoint.last_durable_stream_sequence is None
    assert checkpoint.last_event_id is None
    assert store.high_watermarks_at_save == [None]
    assert context.event_emitter.last_accepted_sequence == 1


def test_checkpoint_created_is_not_emitted_when_checkpoint_save_fails(
    tmp_path: Path,
) -> None:
    context, event_store = _context(tmp_path, run_id="run-checkpoint-failure")
    context.recorder.emit(
        "workflow_started",
        {"workflow_version": context.workflow.version, "profile": context.profile},
        trace_context=context.trace_context,
    )

    with pytest.raises(OSError, match="checkpoint storage unavailable"):
        CheckpointCoordinator(checkpoint_store=_FailingStore()).write_checkpoint(
            run_id=context.run_id,
            workflow=context.workflow,
            profile=context.profile,
            current_step_ids=["s1"],
            buffer=context.buffer,
            step_results=context.step_results,
            path=context.path,
            recorder=_NoListRecorder(context.recorder),
            manifest=context.manifest,
            checkpoint_ids=context.checkpoint_ids,
            trace_context=context.trace_context,
        )

    assert event_store.get_stream_high_watermark(context.event_emitter.stream_id) == 1
    assert context.checkpoint_ids == []
    assert context.manifest["checkpoint_refs"] == []


def test_local_store_atomically_round_trips_v2_without_v1_coercion(
    tmp_path: Path,
) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    checkpoint = _durable_checkpoint()

    path = store.save_checkpoint(checkpoint)
    payload = json.loads(path.read_text(encoding="utf-8"))
    restored = store.get_checkpoint(checkpoint.run_id, checkpoint.checkpoint_id)

    assert payload["schema_version"] == CHECKPOINT_SCHEMA_VERSION_V2
    assert isinstance(restored, DurableWorkflowCheckpoint)
    assert restored == checkpoint


def test_local_store_atomic_replace_failure_preserves_previous_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    checkpoint = _durable_checkpoint()
    path = store.save_checkpoint(checkpoint)
    original = path.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(checkpoint_store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save_checkpoint(
            replace(checkpoint, metadata={"profile": "replacement"})
        )

    assert path.read_bytes() == original
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_local_store_preserves_legacy_v1_saved_model_reads(tmp_path: Path) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    legacy = WorkflowCheckpoint(
        checkpoint_id="cp-legacy",
        run_id="run-legacy",
        workflow_id="workflow-legacy",
        workflow_version="1",
        current_step_ids=["s1"],
        data_buffer_snapshot={"value": 1},
        event_offset=0,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    store.save_checkpoint(legacy)
    restored = store.get_checkpoint(legacy.run_id, legacy.checkpoint_id)

    assert isinstance(restored, WorkflowCheckpoint)
    assert restored == legacy


def test_local_store_rejects_v2_fields_without_an_explicit_schema(
    tmp_path: Path,
) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    checkpoint = _durable_checkpoint()
    path = store.save_checkpoint(checkpoint)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("schema_version")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing schema_version"):
        store.get_checkpoint(checkpoint.run_id, checkpoint.checkpoint_id)


def test_local_store_rejects_a_tampered_v2_boundary(tmp_path: Path) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    checkpoint = _durable_checkpoint()
    path = store.save_checkpoint(checkpoint)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["last_event_id"] = "event-tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum is invalid"):
        store.get_checkpoint(checkpoint.run_id, checkpoint.checkpoint_id)


def test_recovery_cursor_verifies_store_boundary_and_excludes_it(
    tmp_path: Path,
) -> None:
    context, event_store = _context(tmp_path, run_id="run-recovery-cursor")
    boundary = context.event_emitter.emit_default(
        "workflow_started",
        {"workflow_version": context.workflow.version, "profile": context.profile},
    )
    later = context.event_emitter.emit_default(
        "checkpoint_created",
        {"checkpoint_id": "cp-later", "current_step_ids": ["s1"], "path": []},
    )
    checkpoint = DurableWorkflowCheckpoint(
        checkpoint_id="cp-boundary",
        run_id=context.run_id,
        workflow_id=context.workflow.workflow_id,
        workflow_version=context.workflow.version,
        current_step_ids=["s1"],
        data_buffer_snapshot={"request": {}},
        stream_id=context.event_emitter.stream_id,
        last_durable_stream_sequence=boundary.stream_sequence,
        last_event_id=boundary.event_id,
    )

    cursor = verified_checkpoint_recovery_cursor(
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        reader=event_store,
    )

    assert cursor.after_sequence == boundary.stream_sequence
    assert not cursor.should_apply(boundary.stream_sequence)
    assert cursor.should_apply(later.stream_sequence)


def _context(
    tmp_path: Path,
    *,
    run_id: str,
) -> tuple[WorkflowExecutionContext, SQLiteEventStore]:
    workflow = WorkflowSpec(
        workflow_id="workflow-checkpoint-v2",
        name="Checkpoint v2",
        version="2",
        steps=[StepSpec(step_id="s1", write_keys=["ok"])],
        terminal_step_ids=["s1"],
    )
    event_store = SQLiteEventStore(tmp_path / f"{run_id}.sqlite3")
    catalog = default_event_schema_catalog()
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        step_runner_registry=StepRunnerRegistry(),
        event_runtime=EventRuntime(store=event_store, schema_catalog=catalog),
        event_reader=event_store,
        event_schema_catalog=catalog,
        started_monotonic=0.0,
        run_id=run_id,
    )
    return context, event_store


def _durable_checkpoint() -> DurableWorkflowCheckpoint:
    return DurableWorkflowCheckpoint(
        checkpoint_id="cp-durable",
        run_id="run-durable",
        workflow_id="workflow-durable",
        workflow_version="2",
        current_step_ids=["s1"],
        data_buffer_snapshot={"value": 1},
        stream_id="run:run-durable",
        last_durable_stream_sequence=3,
        last_event_id="event-3",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        metadata={"profile": "test"},
    )
