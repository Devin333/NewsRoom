from __future__ import annotations

from framework.harness import (
    HarnessCheckpoint,
    HarnessRunSpec,
    HarnessState,
    HarnessStepSpec,
    InMemoryHarnessCheckpointStore,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec


def test_checkpoint_store_roundtrips_and_verifies_checksum() -> None:
    state = _state()
    checkpoint = HarnessCheckpoint(
        checkpoint_id="checkpoint-1",
        run_id="run-checkpoint",
        state=state,
        last_event_id="event-1",
    )
    store = InMemoryHarnessCheckpointStore()

    store.save_checkpoint(checkpoint)
    loaded = store.load_checkpoint("checkpoint-1")

    assert loaded.checksum.startswith("sha256:")
    assert store.restore_state("checkpoint-1").run_spec.run_id == "run-checkpoint"


def test_checkpoint_store_rejects_checksum_mismatch() -> None:
    checkpoint = HarnessCheckpoint(
        checkpoint_id="checkpoint-bad",
        run_id="run-checkpoint",
        state=_state(),
        checksum="sha256:bad",
    )

    try:
        InMemoryHarnessCheckpointStore().save_checkpoint(checkpoint)
    except Exception as exc:
        assert exc.__class__.__name__ == "HarnessValidationError"
    else:
        raise AssertionError("expected HarnessValidationError")


def _state() -> HarnessState:
    workflow = HarnessWorkflowSpec(
        workflow_id="wf-checkpoint",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )
    return HarnessState.initial(HarnessRunSpec(run_id="run-checkpoint", workflow=workflow))
