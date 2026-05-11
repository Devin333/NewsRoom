from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.local_json import LatestReportRecord, LocalJsonRepository, ReportSearchRecord


@dataclass(frozen=True)
class ReportSearchResultSet:
    query: str
    limit: int
    reports: list[ReportSearchRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "limit": self.limit,
            "report_count": len(self.reports),
            "reports": [report.to_dict() for report in self.reports],
        }


class ReportApplicationService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.repository = LocalJsonRepository(artifact_root)

    def latest_report(self) -> LatestReportRecord:
        return self.repository.latest_report()

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
