from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.layers.output.report_quality_projection import (
    normalize_quality_result_records,
    project_report_quality_payload,
)
from interfaces.models.common import ApiActionResult
from infrastructure.storage.lineage.evidence import quality_lineage_summary
from infrastructure.storage.local_json import LocalJsonRepository

_DEFAULT_ARTIFACT_ROOT = Path(".newsroom/runs")


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
    graph_id: str | None = None
    graph_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "graph_id": self.graph_id,
            "graph_ids": list(self.graph_ids) if self.graph_ids is not None else None,
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
        graph_id: str | None = None,
        graph_ids: tuple[str, ...] | None = None,
    ) -> ReportListResultSet:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if graph_id and graph_ids:
            raise ValueError("graph_id and graph_ids are mutually exclusive")
        if graph_ids is not None and not graph_ids:
            raise ValueError("graph_ids must not be empty")
        return ReportListResultSet(
            limit=limit,
            graph_id=graph_id,
            graph_ids=graph_ids,
            reports=self.repository.list_reports(
                limit=limit,
                graph_id=graph_id,
                graph_ids=graph_ids,
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
        quality_results = _quality_result_records(self.repository, record.run_id)
        quality = project_report_quality_payload(
            record.report_json,
            quality_records=quality_results,
        )
        return ReportQualityResult(
            report_id=record.report_id,
            run_id=record.run_id,
            status=record.status,
            quality_score=record.quality_score,
            quality={
                **quality,
                "quality_lineage": _quality_lineage_payload(
                    self.repository,
                    record.run_id,
                    record.report_id,
                    quality_results=quality_results,
                ),
            },
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
    dsn = database_dsn or (
        values.get("NEWS_DATABASE_DSN")
        if env is not None or Path(artifact_root) == _DEFAULT_ARTIFACT_ROOT
        else None
    )
    if dsn:
        from infrastructure.storage.postgres import PostgresRepository

        return PostgresRepository(dsn)
    return LocalJsonRepository(artifact_root)


def _quality_lineage_payload(
    repository: Any,
    run_id: str,
    report_id: str,
    *,
    quality_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    list_claims = getattr(repository, "list_claims", None)
    raw_claims = list_claims(run_id) if callable(list_claims) else []
    claims = [dict(item) for item in raw_claims] if isinstance(raw_claims, list) else []
    resolved_quality_results = quality_results
    if resolved_quality_results is None:
        resolved_quality_results = _quality_result_records(repository, run_id)
    return quality_lineage_summary(
        run_id=run_id,
        report_id=report_id,
        claims=claims,
        quality_results=resolved_quality_results,
    )


def _quality_result_records(repository: Any, run_id: str) -> list[dict[str, Any]]:
    list_quality_results = getattr(repository, "list_quality_results", None)
    raw_quality_results = list_quality_results(run_id) if callable(list_quality_results) else []
    return normalize_quality_result_records(raw_quality_results)
