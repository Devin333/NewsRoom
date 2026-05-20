from __future__ import annotations

import json
from pathlib import Path

from infrastructure.storage.checkpoint.models import WorkflowCheckpoint


class CheckpointNotFoundError(FileNotFoundError):
    pass


class LocalJsonCheckpointStore:
    def __init__(self, root: str | Path = ".newsroom/checkpoints") -> None:
        self.root = Path(root)

    def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> Path:
        _validate_id(checkpoint.run_id, "run_id")
        _validate_id(checkpoint.checkpoint_id, "checkpoint_id")
        path = self._checkpoint_path(checkpoint.run_id, checkpoint.checkpoint_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(checkpoint.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def get_latest_checkpoint(self, run_id: str) -> WorkflowCheckpoint | None:
        checkpoints = self.list_checkpoints(run_id)
        if not checkpoints:
            return None
        return sorted(
            checkpoints,
            key=lambda checkpoint: (checkpoint.created_at, checkpoint.checkpoint_id),
            reverse=True,
        )[0]

    def list_checkpoints(self, run_id: str) -> list[WorkflowCheckpoint]:
        _validate_id(run_id, "run_id")
        run_dir = self.root / run_id
        if not run_dir.exists():
            return []
        checkpoints = []
        for path in sorted(run_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            checkpoints.append(WorkflowCheckpoint.from_dict(payload))
        return checkpoints

    def get_checkpoint(self, run_id: str, checkpoint_id: str) -> WorkflowCheckpoint:
        path = self._checkpoint_path(run_id, checkpoint_id)
        if not path.exists():
            raise CheckpointNotFoundError(f"checkpoint not found: {run_id}/{checkpoint_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowCheckpoint.from_dict(payload)

    def _checkpoint_path(self, run_id: str, checkpoint_id: str) -> Path:
        _validate_id(run_id, "run_id")
        _validate_id(checkpoint_id, "checkpoint_id")
        return self.root / run_id / f"{checkpoint_id}.json"


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")
