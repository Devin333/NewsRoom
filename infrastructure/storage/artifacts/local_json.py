from __future__ import annotations

import json
from pathlib import Path

from framework.agent.artifacts.models import ArtifactRef
from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.shared.hashing import hash_text


class ArtifactIndexNotFoundError(FileNotFoundError):
    pass


class LocalJsonArtifactIndexStore:
    def __init__(self, root: str | Path = ".newsroom/runs/_records/artifact_index") -> None:
        self.root = Path(root)

    def index_artifact(self, ref: ArtifactRef) -> Path:
        validate_artifact_path_segment(ref.run_id, field="run_id")
        _require_artifact_id(ref.artifact_id)
        if ref.step_id is not None:
            validate_artifact_path_segment(ref.step_id, field="step_id")
        validate_relative_artifact_path(ref.path, field="artifact path")

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
        validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(
            self.root,
            _run_dir_name(run_id),
            field="run_id",
        )
        if not run_dir.exists():
            return []
        refs = [
            ArtifactRef.from_dict(
                json.loads(
                    resolve_artifact_descendant(
                        run_dir,
                        candidate.name,
                        field="artifact index record",
                    ).read_text(encoding="utf-8")
                )
            )
            for candidate in run_dir.glob("*.json")
        ]
        return sorted(refs, key=lambda ref: (ref.created_at, ref.artifact_id))

    def list_all(self) -> list[ArtifactRef]:
        if not self.root.exists():
            return []
        refs = []
        for candidate_run_dir in sorted(self.root.iterdir()):
            run_dir = resolve_artifact_descendant(
                self.root,
                candidate_run_dir.name,
                field="artifact index run directory",
            )
            if not run_dir.is_dir():
                continue
            for candidate in sorted(run_dir.glob("*.json")):
                path = resolve_artifact_descendant(
                    run_dir,
                    candidate.name,
                    field="artifact index record",
                )
                refs.append(ArtifactRef.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return sorted(refs, key=lambda ref: (ref.run_id, ref.created_at, ref.artifact_id))

    def list_by_step(self, run_id: str, step_id: str) -> list[ArtifactRef]:
        validate_artifact_path_segment(step_id, field="step_id")
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
        validate_artifact_path_segment(run_id, field="run_id")
        artifact_id = _require_artifact_id(artifact_id)
        return resolve_artifact_descendant(
            self.root,
            _run_dir_name(run_id),
            _record_file_name(artifact_id),
            field="artifact index record",
        )


def _run_dir_name(run_id: str) -> str:
    return hash_text(run_id)[:12]


def _record_file_name(artifact_id: str) -> str:
    digest = hash_text(artifact_id)[:16]
    return f"a-{digest}.json"


def _require_artifact_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_id is required")
    return value
