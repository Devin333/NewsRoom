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


@dataclass(frozen=True)
class RunEventsResult:
    run_id: str
    events: list[dict[str, Any]]
    events_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
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

    def get_run_events(self, run_id: str, *, limit: int | None = None) -> RunEventsResult:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        detail = self.get_run(run_id)
        artifacts = detail.manifest.get("artifacts") or {}
        if "events" not in artifacts:
            raise FileNotFoundError(f"events artifact not found for run: {run_id}")
        events_path = _artifact_path(self.artifact_root, run_id, str(artifacts["events"]))
        events = _read_jsonl_events(events_path)
        if limit is not None:
            events = events[:limit]
        return RunEventsResult(
            run_id=detail.run_id,
            events=[_redact_sensitive_keys(event) for event in events],
            events_path=str(events_path),
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


def _read_jsonl_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"event line must be a JSON object: {line_number}")
            events.append(payload)
    return events


def _artifact_path(artifact_root: Path, run_id: str, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid artifact path: {relative_path}")
    path = artifact_root / run_id / relative
    if not path.exists():
        raise FileNotFoundError(f"artifact file not found: {relative_path}")
    return path


def _redact_sensitive_keys(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact_sensitive_keys(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_keys(item) for item in value]
    return value


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    sensitive_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    )
    return any(fragment in normalized for fragment in sensitive_fragments)


def _validate_run_id(run_id: str) -> None:
    relative = Path(run_id)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid run id: {run_id}")
