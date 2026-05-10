from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    workflow_id: str | None = None
    workflow_version: str | None = None
    profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    quality_score: float | None = None
    step_count: int | None = None
    event_count: int | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "profile": self.profile,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "quality_score": self.quality_score,
            "step_count": self.step_count,
            "event_count": self.event_count,
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class RunListResult:
    runs: list[RunSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"run_count": len(self.runs), "runs": [run.to_dict() for run in self.runs]}


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
        }


class RunInspectionService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def list_runs(self, *, limit: int = 20) -> RunListResult:
        summaries = []
        for manifest_path in self.artifact_root.glob("*/manifest.json"):
            try:
                manifest = _read_json(manifest_path)
                summaries.append(_summary_from_manifest(manifest, manifest_path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        summaries.sort(key=lambda run: run.started_at or "", reverse=True)
        return RunListResult(summaries[:limit])

    def get_run(self, run_id: str) -> RunDetail:
        _validate_run_id(run_id)
        manifest_path = self.artifact_root / run_id / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        manifest = _read_json(manifest_path)
        return RunDetail(
            run_id=str(manifest.get("run_id") or run_id),
            manifest=manifest,
            manifest_path=str(manifest_path),
        )


def _summary_from_manifest(manifest: dict[str, Any], manifest_path: Path) -> RunSummary:
    return RunSummary(
        run_id=str(manifest["run_id"]),
        status=str(manifest.get("status") or "unknown"),
        workflow_id=manifest.get("workflow_id"),
        workflow_version=manifest.get("workflow_version"),
        profile=manifest.get("profile"),
        started_at=manifest.get("started_at"),
        finished_at=manifest.get("finished_at"),
        quality_score=manifest.get("quality_score"),
        step_count=manifest.get("step_count"),
        event_count=manifest.get("event_count"),
        manifest_path=str(manifest_path),
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload


def _validate_run_id(run_id: str) -> None:
    relative = Path(run_id)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid run id: {run_id}")
