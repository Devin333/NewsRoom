from __future__ import annotations

from pathlib import Path
from typing import Callable

from framework import RunResult

from interfaces.services.run_persistence_service import RunPersistenceApplicationService


class WeeklyRunApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        persistence_service: RunPersistenceApplicationService,
        report_service_factory: Callable,
        weekly_runner_cls: Callable,
        profile: str,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.persistence_service = persistence_service
        self.report_service_factory = report_service_factory
        self.weekly_runner_cls = weekly_runner_cls
        self.profile = profile

    def run_weekly(
        self,
        *,
        language: str = "en",
        topic: str | None = None,
        source_limit: int = 20,
        period_start: str | None = None,
        period_end: str | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        repository = self.persistence_service.prepare_repository()
        report_repository = self.report_service_factory(artifact_root=self.artifact_root).repository
        result = self.weekly_runner_cls(
            artifact_root=self.artifact_root,
            report_repository=report_repository,
        ).run(
            language=language,
            topic=topic,
            source_limit=source_limit,
            period_start=period_start,
            period_end=period_end,
            run_id=run_id,
        )
        self.persistence_service.persist_prepared_result(repository, result, profile=self.profile)
        return result


__all__ = ["WeeklyRunApplicationService"]
