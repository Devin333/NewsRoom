from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from storage.local_json import LocalJsonRepository


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
