from __future__ import annotations

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.runtime.checkpoint import HarnessCheckpoint, checkpoint_checksum


class InMemoryHarnessCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, HarnessCheckpoint] = {}
        self._run_index: dict[str, list[str]] = {}

    def save_checkpoint(self, checkpoint: HarnessCheckpoint) -> HarnessCheckpoint:
        self._verify_checksum(checkpoint)
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        self._run_index.setdefault(checkpoint.run_id, []).append(checkpoint.checkpoint_id)
        return checkpoint

    def load_checkpoint(self, checkpoint_id: str) -> HarnessCheckpoint:
        checkpoint = self._checkpoints[checkpoint_id]
        self._verify_checksum(checkpoint)
        return checkpoint

    def latest_for_run(self, run_id: str) -> HarnessCheckpoint | None:
        ids = self._run_index.get(run_id, ())
        if not ids:
            return None
        return self.load_checkpoint(ids[-1])

    def restore_state(self, checkpoint_id: str):
        return self.load_checkpoint(checkpoint_id).state

    def _verify_checksum(self, checkpoint: HarnessCheckpoint) -> None:
        expected = checkpoint_checksum(checkpoint.run_id, checkpoint.state.to_dict(), checkpoint.last_event_id)
        if checkpoint.checksum != expected:
            raise HarnessValidationError(
                "checkpoint checksum mismatch",
                details={"checkpoint_id": checkpoint.checkpoint_id, "expected": expected, "actual": checkpoint.checksum},
            )


__all__ = ["InMemoryHarnessCheckpointStore"]
