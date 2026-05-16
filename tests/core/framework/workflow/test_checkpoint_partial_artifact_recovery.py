from __future__ import annotations

from datetime import UTC, datetime

from core.framework.workflow.checkpointing import (
    envelope_from_checkpoint,
    inspect_checkpoint_artifacts,
)
from storage.checkpoint import WorkflowCheckpoint


def test_checkpoint_artifact_inspection_rejects_missing_manifest_in_strict_mode(tmp_path) -> None:
    report = inspect_checkpoint_artifacts(
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        manifest=None,
        artifact_root=tmp_path,
        strict=True,
    )

    assert report.recoverable is False
    assert "manifest.json" in report.missing_required_artifacts


def test_checkpoint_artifact_inspection_warns_for_optional_missing_artifact(tmp_path) -> None:
    manifest = {
        "artifacts": {
            "events": "events.jsonl",
            "report": "report.md",
        }
    }

    report = inspect_checkpoint_artifacts(
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        manifest=manifest,
        artifact_root=tmp_path,
        strict=False,
    )

    assert report.recoverable is True
    assert "report" in report.missing_optional_artifacts
    assert report.warnings


def test_checkpoint_artifact_inspection_recovers_from_checkpoint_buffer_snapshot(tmp_path) -> None:
    report = inspect_checkpoint_artifacts(
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        manifest=None,
        artifact_root=tmp_path,
        strict=False,
    )

    assert report.recoverable is True
    assert "checkpoint.data_buffer_snapshot" in report.recovered_artifacts


def test_checkpoint_artifact_inspection_requires_some_buffer_snapshot(tmp_path) -> None:
    checkpoint = _checkpoint(data_buffer_snapshot={})

    report = inspect_checkpoint_artifacts(
        checkpoint=envelope_from_checkpoint(checkpoint),
        manifest={},
        artifact_root=tmp_path,
        strict=False,
    )

    assert report.recoverable is False
    assert "data_buffer_snapshot" in report.missing_required_artifacts


def _checkpoint(*, data_buffer_snapshot: dict | None = None) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["review"],
        data_buffer_snapshot=(
            {"request": {"topic": "ai"}}
            if data_buffer_snapshot is None
            else data_buffer_snapshot
        ),
        step_results={"review": {"status": "paused", "outputs": {}}},
        path=["review"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
