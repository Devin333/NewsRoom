from datetime import UTC, datetime

import pytest

from framework.specs import WorkflowStatus
from infrastructure.storage.checkpoint import CheckpointNotFoundError, LocalJsonCheckpointStore, WorkflowCheckpoint


def _checkpoint(checkpoint_id: str, *, created_at: datetime) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1",
        current_step_ids=["draft_report"],
        data_buffer_snapshot={"request": {"topic": "AI"}, "ranked_items": []},
        step_results={"collect_sources": {"status": "succeeded"}},
        path=["collect_sources", "rank_sources"],
        event_offset=7,
        created_at=created_at,
        metadata={"profile": "live"},
    )


def test_workflow_checkpoint_round_trips() -> None:
    checkpoint = _checkpoint("cp-1", created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))

    restored = WorkflowCheckpoint.from_dict(checkpoint.to_dict())

    assert restored == checkpoint
    assert restored.to_dict()["created_at"] == "2026-05-11T01:00:00Z"


def test_workflow_checkpoint_serializes_nested_json_safe_values() -> None:
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1",
        current_step_ids=[],
        data_buffer_snapshot={"status": WorkflowStatus.SUCCEEDED},
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )

    assert checkpoint.to_dict()["data_buffer_snapshot"] == {"status": "succeeded"}


def test_local_json_checkpoint_store_saves_lists_and_reads_latest(tmp_path) -> None:
    store = LocalJsonCheckpointStore(tmp_path)
    older = _checkpoint("cp-1", created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))
    newer = _checkpoint("cp-2", created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC))

    older_path = store.save_checkpoint(older)
    newer_path = store.save_checkpoint(newer)

    assert older_path.exists()
    assert newer_path.exists()
    assert [checkpoint.checkpoint_id for checkpoint in store.list_checkpoints("run-1")] == ["cp-1", "cp-2"]
    assert store.get_checkpoint("run-1", "cp-1") == older
    assert store.get_latest_checkpoint("run-1") == newer


def test_local_json_checkpoint_store_returns_none_when_missing(tmp_path) -> None:
    assert LocalJsonCheckpointStore(tmp_path).get_latest_checkpoint("missing") is None


def test_local_json_checkpoint_store_rejects_unsafe_ids(tmp_path) -> None:
    store = LocalJsonCheckpointStore(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_checkpoints("../secret")

    with pytest.raises(ValueError, match="invalid checkpoint_id"):
        store.get_checkpoint("run-1", "../secret")


def test_local_json_checkpoint_store_raises_for_missing_checkpoint(tmp_path) -> None:
    with pytest.raises(CheckpointNotFoundError):
        LocalJsonCheckpointStore(tmp_path).get_checkpoint("run-1", "missing")
