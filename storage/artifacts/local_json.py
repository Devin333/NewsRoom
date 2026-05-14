from __future__ import annotations

import json
from pathlib import Path

from storage.artifacts.filesystem import _validate_id, _validate_relative_path
from storage.artifacts.models import ArtifactRef


class ArtifactIndexNotFoundError(FileNotFoundError):
    pass


class LocalJsonArtifactIndexStore:
    def __init__(self, root: str | Path = ".newsroom/runs/_records/artifact_index") -> None:
        self.root = Path(root)

    def index_artifact(self, ref: ArtifactRef) -> Path:
        _validate_id(ref.run_id, "run_id")
        _validate_id(ref.artifact_id, "artifact_id")
        if ref.step_id is not None:
            _validate_id(ref.step_id, "step_id")
        _validate_relative_path(ref.path)

        path = self._record_path(ref.run_id, ref.artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(ref.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def get_artifact(self, run_id: str, artifact_id: str) -> ArtifactRef:
        path = self._record_path(run_id, artifact_id)
        if not path.exists():
            raise ArtifactIndexNotFoundError(f"artifact index record not found: {run_id}/{artifact_id}")
        return ArtifactRef.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_by_run(self, run_id: str) -> list[ArtifactRef]:
        _validate_id(run_id, "run_id")
        run_dir = self.root / run_id
        if not run_dir.exists():
            return []
        refs = [ArtifactRef.from_dict(json.loads(path.read_text(encoding="utf-8"))) for path in run_dir.glob("*.json")]
        return sorted(refs, key=lambda ref: (ref.created_at, ref.artifact_id))

    def list_all(self) -> list[ArtifactRef]:
        if not self.root.exists():
            return []
        refs = []
        for run_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            for path in sorted(run_dir.glob("*.json")):
                refs.append(ArtifactRef.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return sorted(refs, key=lambda ref: (ref.run_id, ref.created_at, ref.artifact_id))

    def list_by_step(self, run_id: str, step_id: str) -> list[ArtifactRef]:
        _validate_id(step_id, "step_id")
        return [ref for ref in self.list_by_run(run_id) if ref.step_id == step_id]

    def list_by_type(self, artifact_type: str, *, run_id: str | None = None) -> list[ArtifactRef]:
        if not artifact_type:
            raise ValueError("artifact_type is required")
        if run_id is not None:
            return [ref for ref in self.list_by_run(run_id) if ref.artifact_type == artifact_type]
        return [ref for ref in self.list_all() if ref.artifact_type == artifact_type]

    def delete_artifact(self, run_id: str, artifact_id: str) -> None:
        path = self._record_path(run_id, artifact_id)
        if path.exists():
            path.unlink()

    def _record_path(self, run_id: str, artifact_id: str) -> Path:
        _validate_id(run_id, "run_id")
        _validate_id(artifact_id, "artifact_id")
        return self.root / run_id / f"{artifact_id}.json"
