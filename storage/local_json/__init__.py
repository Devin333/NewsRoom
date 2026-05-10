"""Local JSON storage package."""

from storage.local_json.repository import LatestReportRecord, LocalJsonRepository, ReportNotFoundError

__all__ = ["LatestReportRecord", "LocalJsonRepository", "ReportNotFoundError"]
