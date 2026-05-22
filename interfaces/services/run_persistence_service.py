from __future__ import annotations

from pathlib import Path
from typing import Callable

from framework import RunResult


class RunPersistenceApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        repository_factory: Callable,
        persist_result: Callable,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.repository_factory = repository_factory
        self.persist_result = persist_result

    def prepare_repository(self):
        repository = self.repository_factory(artifact_root=self.artifact_root)
        repository.migrate()
        return repository

    def persist_prepared_result(self, repository, result: RunResult, *, profile: str) -> None:
        self.persist_result(
            repository,
            result,
            profile=profile,
            migrate=False,
        )

    def persist_result_after_migration(self, result: RunResult, *, profile: str) -> None:
        repository = self.prepare_repository()
        self.persist_prepared_result(repository, result, profile=profile)


__all__ = ["RunPersistenceApplicationService"]
