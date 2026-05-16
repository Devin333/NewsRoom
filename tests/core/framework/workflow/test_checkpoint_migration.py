from __future__ import annotations

import pytest

from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow.checkpointing import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointMigrationRegistry,
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    check_checkpoint_compatibility,
    default_checkpoint_migration_registry,
    verify_checkpoint_checksum,
)


def test_checkpoint_v0_migrates_to_current_schema() -> None:
    envelope = default_checkpoint_migration_registry().migrate_to_current(_v0_payload())

    assert envelope.schema_version == CHECKPOINT_SCHEMA_VERSION
    assert envelope.manifest_hash is None
    assert envelope.metadata["migrations"]


def test_checkpoint_migration_recomputes_checksum() -> None:
    payload = _v0_payload()
    payload["checksum"] = "stale"

    envelope = default_checkpoint_migration_registry().migrate_to_current(payload)

    assert envelope.checksum != "stale"
    assert verify_checkpoint_checksum(envelope) is True


def test_checkpoint_migration_records_history() -> None:
    envelope = default_checkpoint_migration_registry().migrate_to_current(_v0_payload())

    assert envelope.metadata["migrations"] == [
        {
            "source_schema_version": "workflow-checkpoint/v0",
            "target_schema_version": CHECKPOINT_SCHEMA_VERSION,
        }
    ]


def test_checkpoint_unknown_schema_without_migration_fails() -> None:
    payload = _v0_payload()
    payload["schema_version"] = "workflow-checkpoint/unknown"

    with pytest.raises(ValueError, match="no checkpoint migration path"):
        CheckpointMigrationRegistry().migrate_to_current(payload)


def test_checkpoint_migration_still_checks_workflow_identity() -> None:
    payload = _v0_payload()
    payload["workflow_id"] = "other"
    envelope = default_checkpoint_migration_registry().migrate_to_current(payload)

    result = check_checkpoint_compatibility(envelope=envelope, workflow=_workflow())

    assert result.compatible is False
    assert any("workflow_id" in error for error in result.errors)


def test_checkpoint_migration_metadata_is_carried_into_resume_plan() -> None:
    envelope = default_checkpoint_migration_registry().migrate_to_current(_v0_payload())

    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(mode=ResumeMode.EXACT, checkpoint=envelope),
    )

    assert plan.resume_metadata["checkpoint_migrations"] == [
        {
            "source_schema_version": "workflow-checkpoint/v0",
            "target_schema_version": CHECKPOINT_SCHEMA_VERSION,
        }
    ]


def _v0_payload() -> dict:
    return {
        "checkpoint_id": "cp-v0",
        "run_id": "run-v0",
        "workflow_id": "daily",
        "workflow_version": "1.0",
        "current_step_ids": ["write"],
        "data_buffer_snapshot": {"request": {"topic": "ai"}, "plan": "outline"},
        "step_results": {
            "plan": {"status": "succeeded", "outputs": {"plan": "outline"}},
        },
        "path": ["plan"],
        "created_at": "2026-05-16T01:02:03Z",
    }


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="write",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="sample.plan",
                read_keys=["request"],
                write_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="sample.write",
                read_keys=["plan"],
                write_keys=["report"],
            ),
        ],
        metadata={"initial_keys": ["plan"]},
    )
