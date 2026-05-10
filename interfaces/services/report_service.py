from __future__ import annotations

from pathlib import Path

from storage.local_json import LatestReportRecord, LocalJsonRepository


class ReportApplicationService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.repository = LocalJsonRepository(artifact_root)

    def latest_report(self) -> LatestReportRecord:
        return self.repository.latest_report()
