from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.artifacts.models import Artifact, ArtifactReference
from framework.artifacts.stores import ArtifactStore, LocalArtifactStore
from framework.shared.json import to_jsonable


class ArtifactManager:
    def __init__(
        self,
        root: str | Path,
        *,
        store: ArtifactStore | None = None,
    ) -> None:
        self.root = Path(root)
        self.store = store or LocalArtifactStore(self.root)

    def publish(self, artifact: Artifact) -> ArtifactReference:
        return self.store.put(artifact)

    def resolve(self, ref: ArtifactReference) -> Artifact:
        artifact = self.store.get(ref.artifact_id)
        if artifact is None:
            raise FileNotFoundError(f"artifact not found: {ref.artifact_id}")
        return artifact

    def list(self, run_id: str | None = None) -> list[ArtifactReference]:
        return self.store.list(prefix=run_id)

    def delete(self, artifact_id: str) -> None:
        self.store.delete(artifact_id)

    def start_run(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def write_json(self, run_id: str, name: str, data: Any) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(to_jsonable(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def write_text(self, run_id: str, name: str, text: str) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def write_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def _target(self, run_id: str, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the run directory: {name}")
        return self.run_dir(run_id) / relative
