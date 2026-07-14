from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.workflow.inspection import read_strict_workflow_artifact_content
from interfaces.services.run_inspection_service import RunInspectionService


@dataclass(frozen=True)
class ArtifactSummary:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ArtifactListResult:
    run_id: str
    artifacts: list[ArtifactSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_count": len(self.artifacts),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class ArtifactDetail:
    run_id: str
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    content: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "content": self.content,
        }


class ArtifactInspectionService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.run_inspection = RunInspectionService(self.artifact_root)

    def list_artifacts(self, run_id: str) -> ArtifactListResult:
        manifest = self.run_inspection.get_run(run_id).manifest
        artifacts = [
            self._summary(run_id, key, relative_path)
            for key, relative_path in sorted((manifest.get("artifacts") or {}).items())
        ]
        return ArtifactListResult(run_id=run_id, artifacts=artifacts)

    def get_artifact(self, run_id: str, artifact_key: str) -> ArtifactDetail:
        run = self.run_inspection.get_run(run_id)
        run_dir = Path(run.artifact_dir or self.artifact_root / run_id)
        record = read_strict_workflow_artifact_content(
            run_dir,
            run.manifest,
            artifact_key,
            redact=True,
        )
        content = record.content
        if record.content_type == "application/x-ndjson" and isinstance(content, list):
            content = _jsonl_values_to_text(content)
        return ArtifactDetail(
            run_id=run_id,
            artifact_key=artifact_key,
            relative_path=record.relative_path,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            content=content,
        )

    def _summary(self, run_id: str, artifact_key: str, relative_path: str) -> ArtifactSummary:
        path = self._artifact_path(run_id, relative_path)
        return ArtifactSummary(
            artifact_key=artifact_key,
            relative_path=relative_path,
            content_type=_content_type(path),
            size_bytes=path.stat().st_size if path.exists() else None,
        )

    def _artifact_path(self, run_id: str, relative_path: str) -> Path:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(
            self.artifact_root,
            safe_run_id,
            field="run_id",
        )
        safe_relative_path = validate_relative_artifact_path(
            relative_path,
            field="artifact path",
        )
        path = resolve_artifact_descendant(
            run_dir,
            safe_relative_path,
            field="artifact path",
        )
        if not path.exists():
            raise FileNotFoundError(f"artifact file not found: {relative_path}")
        return path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain"


def _jsonl_values_to_text(values: list[Any]) -> str:
    lines = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values]
    return "\n".join(lines) + ("\n" if lines else "")
