from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interfaces.models.common import ApiActionResult
from storage.local_json import LocalJsonRepository
from workflows.daily_intelligence.profiles import daily_workflow_ids


@dataclass(frozen=True)
class ReportSearchResultSet:
    query: str
    limit: int
    reports: list[Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "limit": self.limit,
            "report_count": len(self.reports),
            "reports": [report.to_dict() for report in self.reports],
        }


@dataclass(frozen=True)
class ReportListResultSet:
    limit: int
    reports: list[Any]
    workflow_id: str | None = None
    workflow_family: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "workflow_id": self.workflow_id,
            "workflow_family": self.workflow_family,
            "report_count": len(self.reports),
            "reports": [report.to_dict() for report in self.reports],
        }


@dataclass(frozen=True)
class ReportMarkdownResult:
    report_id: str
    run_id: str
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "markdown": self.markdown,
        }


@dataclass(frozen=True)
class ReportQualityResult:
    report_id: str
    run_id: str
    status: str
    quality_score: float | None
    quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "quality_score": self.quality_score,
            "quality": dict(self.quality),
        }


class ReportApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        repository: Any | None = None,
        database_dsn: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.repository = repository or _report_repository(
            artifact_root=artifact_root,
            database_dsn=database_dsn,
            env=env,
        )

    def latest_report(self) -> Any:
        return self.repository.latest_report()

    def get_report(self, report_id: str) -> Any:
        if not report_id:
            raise ValueError("report_id is required")
        return self.repository.get_report(report_id)

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_family: str | None = None,
    ) -> ReportListResultSet:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if workflow_id and workflow_family:
            raise ValueError("workflow_id and workflow_family are mutually exclusive")
        return ReportListResultSet(
            limit=limit,
            workflow_id=workflow_id,
            workflow_family=workflow_family,
            reports=self.repository.list_reports(
                limit=limit,
                workflow_id=workflow_id,
                workflow_ids=_workflow_ids_for_family(workflow_family),
            ),
        )

    def search_reports(self, *, query: str, limit: int = 20) -> ReportSearchResultSet:
        if not query:
            raise ValueError("query is required")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        return ReportSearchResultSet(
            query=query,
            limit=limit,
            reports=self.repository.search_reports(query, limit=limit),
        )

    def report_markdown(self, report_id: str) -> ReportMarkdownResult:
        record = self.get_report(report_id)
        markdown = record.report_markdown
        if markdown is None:
            raise FileNotFoundError(f"report markdown not found: {report_id}")
        return ReportMarkdownResult(
            report_id=record.report_id,
            run_id=record.run_id,
            markdown=markdown,
        )

    def report_quality(self, report_id: str) -> ReportQualityResult:
        record = self.get_report(report_id)
        return ReportQualityResult(
            report_id=record.report_id,
            run_id=record.run_id,
            status=record.status,
            quality_score=record.quality_score,
            quality=_quality_payload(record.report_json),
        )

    def request_review(
        self,
        report_id: str,
        *,
        requested_by: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApiActionResult:
        record = self.get_report(report_id)
        return ApiActionResult(
            action="request_report_review",
            resource_type="report",
            resource_id=record.report_id,
            status="requested",
            message="report review requested",
            metadata={
                "run_id": record.run_id,
                "requested_by": requested_by,
                "reason": reason,
                **(metadata or {}),
            },
        )

    def publish_report(
        self,
        report_id: str,
        *,
        requested_by: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApiActionResult:
        record = self.get_report(report_id)
        return ApiActionResult(
            action="publish_report",
            resource_type="report",
            resource_id=record.report_id,
            status="approval_required",
            message="report publish requires approval before external delivery",
            metadata={
                "run_id": record.run_id,
                "requested_by": requested_by,
                "reason": reason,
                **(metadata or {}),
            },
        )


def _report_repository(
    *,
    artifact_root: str | Path,
    database_dsn: str | None,
    env: dict[str, str] | None,
) -> Any:
    values = env if env is not None else os.environ
    dsn = database_dsn or values.get("NEWS_DATABASE_DSN")
    if dsn:
        from storage.postgres import PostgresRepository

        return PostgresRepository(dsn)
    return LocalJsonRepository(artifact_root)


def _quality_payload(report_json: Any) -> dict[str, Any]:
    if not isinstance(report_json, dict):
        return {}
    for key in ("quality", "quality_gate", "editor_review", "quality_metrics"):
        value = report_json.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _workflow_ids_for_family(workflow_family: str | None) -> tuple[str, ...] | None:
    if workflow_family is None:
        return None
    normalized = workflow_family.strip().lower()
    if not normalized:
        return None
    if normalized == "daily":
        return daily_workflow_ids()
    raise ValueError(f"unsupported workflow_family: {workflow_family}")
