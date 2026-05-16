from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow import FunctionStepRegistry, FunctionStepRunner, WorkflowExecutor
from core.framework.workflow.checkpointing import (
    attach_checkpoint_checksum,
    checkpoint_checksum_payload,
    compute_checkpoint_checksum,
    envelope_from_checkpoint,
    verify_checkpoint_checksum,
)
from core.framework.workflow.step_runner import StepExecutionError
from storage.checkpoint import WorkflowCheckpoint


def test_checkpoint_checksum_is_stable() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())

    first = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))
    second = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))

    assert first == second == envelope.checksum


def test_checkpoint_checksum_detects_buffer_mutation() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())
    corrupted = replace(
        envelope,
        data_buffer_snapshot={**envelope.data_buffer_snapshot, "plan": "tampered"},
    )

    assert verify_checkpoint_checksum(corrupted) is False


def test_checkpoint_checksum_detects_current_step_mutation() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())
    corrupted = replace(envelope, current_step_ids=["publish"])

    assert verify_checkpoint_checksum(corrupted) is False


def test_checkpoint_checksum_ignores_runtime_metadata_and_protects_marked_metadata() -> None:
    envelope = envelope_from_checkpoint(
        replace(
            _checkpoint(),
            metadata={
                "profile": "test",
                "runtime_only": {"lease_id": "lease-1"},
                "protected": {"tenant": "newsroom"},
            },
        )
    )
    runtime_changed = replace(
        envelope,
        metadata={
            **envelope.metadata,
            "runtime_only": {"lease_id": "lease-2"},
        },
    )
    protected_changed = attach_checkpoint_checksum(
        replace(
            envelope,
            metadata={
                **envelope.metadata,
                "protected": {"tenant": "other"},
            },
        )
    )

    assert verify_checkpoint_checksum(runtime_changed) is True
    assert protected_changed.checksum != envelope.checksum


def test_checkpoint_checksum_strict_rejects_corruption(tmp_path) -> None:
    checkpoint = _checkpoint()
    envelope = envelope_from_checkpoint(checkpoint)
    corrupted = replace(
        envelope,
        data_buffer_snapshot={**envelope.data_buffer_snapshot, "plan": "tampered"},
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    with pytest.raises(StepExecutionError, match="checksum"):
        executor.resume_from_checkpoint(
            _workflow(),
            checkpoint_from_envelope(corrupted),
            profile="test",
        )


def checkpoint_from_envelope(envelope):
    from core.framework.workflow.checkpointing import envelope_to_checkpoint

    return envelope_to_checkpoint(envelope)


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
