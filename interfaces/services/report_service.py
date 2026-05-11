from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.local_json import LocalJsonRepository


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
