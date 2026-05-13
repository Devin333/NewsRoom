from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.framework.workflow.inspection import (
    WorkflowArtifactContentRecord,
    WorkflowReplayContentBundle,
    WorkflowRunInspectionError,
    WorkflowRunInspector,
    WorkflowRunListItem,
    redact_sensitive_values,
    resolve_run_dir,
)


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


@dataclass(frozen=True)
class RunReplayArtifact:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    content: Any = None
    read_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "content": self.content,
            "read_error": self.read_error,
        }


@dataclass(frozen=True)
class RunReplayResult:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    events: list[dict[str, Any]]
    events_path: str | None
    artifacts: list[RunReplayArtifact]
    events_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
            "events_error": self.events_error,
            "artifact_count": len(self.artifacts),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


class RunInspectionService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self._inspector = WorkflowRunInspector(self.artifact_root)

    def list_runs(self, *, limit: int = 20) -> RunListResult:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        catalog = self._inspector.list_runs(limit=limit, include_invalid=True)
        return RunListResult(
            [
                _summary_from_run_item(item)
                for item in catalog.runs
                if not _is_unreadable_manifest(item)
            ]
        )

    def get_run(self, run_id: str) -> RunDetail:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        manifest = self._inspector.load_manifest(run_dir)
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
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        try:
            event_records = self._inspector.read_events(run_dir, manifest=detail.manifest)
            events = [redact_sensitive_values(event.to_dict()) for event in event_records]
            events_path = self._inspector.artifact_path(
                run_dir,
                "events",
                manifest=detail.manifest,
            )
        except WorkflowRunInspectionError as exc:
            if "not found" in str(exc):
                raise FileNotFoundError(str(exc)) from exc
            raise ValueError(str(exc)) from exc
        if limit is not None:
            events = events[:limit]
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=str(events_path),
        )

    def replay_run(self, run_id: str) -> RunReplayResult:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        if not (run_dir / "manifest.json").exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        bundle = self._inspector.build_replay_content_bundle(run_dir=run_dir, redact=True)
        return _replay_result_from_content_bundle(bundle)


def _summary_from_run_item(item: WorkflowRunListItem) -> RunSummary:
    return RunSummary(
        run_id=item.run_id,
        status=str(item.status or "unknown"),
        workflow_id=item.workflow_id,
        workflow_version=item.workflow_version,
        profile=item.profile,
        started_at=item.started_at,
        finished_at=item.finished_at,
        step_count=item.step_count,
        event_count=item.event_count,
        manifest_path=item.manifest_path,
    )


def _is_unreadable_manifest(item: WorkflowRunListItem) -> bool:
    return bool(item.invalid_reason and "invalid JSON artifact" in item.invalid_reason)


def _replay_result_from_content_bundle(bundle: WorkflowReplayContentBundle) -> RunReplayResult:
    return RunReplayResult(
        run_id=str(bundle.run_id or "unknown"),
        manifest=dict(bundle.manifest),
        manifest_path=bundle.manifest_path,
        events=[dict(event) for event in bundle.events],
        events_path=bundle.events_path,
        events_error=bundle.events_error,
        artifacts=[
            _replay_artifact_from_content_record(artifact)
            for artifact in bundle.artifacts
        ],
    )


def _replay_artifact_from_content_record(
    artifact: WorkflowArtifactContentRecord,
) -> RunReplayArtifact:
    return RunReplayArtifact(
        artifact_key=artifact.artifact_key,
        relative_path=artifact.relative_path,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        content=artifact.content,
        read_error=artifact.read_error,
    )


def _resolve_run_dir_for_service(artifact_root: Path, run_id: str) -> Path:
    try:
        return resolve_run_dir(artifact_root, run_id)
    except WorkflowRunInspectionError as exc:
        raise ValueError(f"invalid run id: {run_id}") from exc
