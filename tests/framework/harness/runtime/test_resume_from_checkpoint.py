from __future__ import annotations

from framework.harness import HarnessCheckpoint, HarnessReplayReader
from tests.framework.harness.runtime.test_checkpoint_store import _state


def test_resume_from_checkpoint_returns_saved_state_without_worker_call() -> None:
    checkpoint = HarnessCheckpoint(checkpoint_id="checkpoint-resume", run_id="run-checkpoint", state=_state())

    state = HarnessReplayReader().resume_from_checkpoint(checkpoint)

    assert state.run_spec.run_id == "run-checkpoint"
    assert state.current_step_id == "collect"
