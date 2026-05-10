from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from storage.local_json import LocalJsonRepository
from core.framework import RunResult


@dataclass(frozen=True)
class WorkflowRunRecord:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: str
    profile: str
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    run_id: str
    status: str
    title: str | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    quality_score: float | None = None
    manifest_path: str | None = None


class PersistenceRepository(Protocol):
    def migrate(self) -> None: ...

    def save_workflow_run(self, record: WorkflowRunRecord) -> None: ...

    def save_report(self, record: ReportRecord) -> None: ...


class LocalJsonPersistenceAdapter:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.local_json = LocalJsonRepository(artifact_root)

    def migrate(self) -> None:
        return None

    def save_workflow_run(self, record: WorkflowRunRecord) -> None:
        return None

    def save_report(self, record: ReportRecord) -> None:
        return None


def repository_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> PersistenceRepository:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from storage.postgres.repository import PostgresRepository

        return PostgresRepository(dsn)
    return LocalJsonPersistenceAdapter(artifact_root)


def workflow_run_record_from_result(result: RunResult, *, profile: str) -> WorkflowRunRecord:
    return WorkflowRunRecord(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        workflow_version=result.workflow_version,
        status=result.status.value,
        profile=profile,
        artifact_dir=result.artifact_dir,
        manifest_path=result.manifest_path,
        events_path=result.events_path,
        error=result.error,
        metrics=_metrics_from_output(result.output),
    )


def report_record_from_result(result: RunResult) -> ReportRecord | None:
    final_report = result.output.get("final_report")
    blocked_report = result.output.get("blocked_report")
    quality_summary = result.output.get("report_quality_summary")
    if final_report is None and blocked_report is None:
        return None

    report_payload = _to_dict(final_report or blocked_report)
    title = report_payload.get("title")
    status = "final" if final_report is not None else "blocked"
    quality_score = None
    quality_payload = _to_dict(quality_summary)
    if quality_payload:
        quality_score = quality_payload.get("quality_score")
    return ReportRecord(
        report_id=f"{result.run_id}:{status}",
        run_id=result.run_id,
        status=status,
        title=title,
        report_json=report_payload,
        report_markdown=result.output.get("report_markdown"),
        quality_score=quality_score,
        manifest_path=result.manifest_path,
    )


def persist_run_result(repository: PersistenceRepository, result: RunResult, *, profile: str) -> None:
    repository.migrate()
    repository.save_workflow_run(workflow_run_record_from_result(result, profile=profile))
    report = report_record_from_result(result)
    if report:
        repository.save_report(report)


def _metrics_from_output(output: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in ["source_pipeline_metrics", "agent_loop_metrics", "report_quality_summary"]:
        if key in output:
            metrics[key] = _to_dict(output[key])
    return metrics


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {}
