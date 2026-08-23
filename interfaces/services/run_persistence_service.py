from __future__ import annotations

from pathlib import Path
from typing import Callable

from infrastructure.storage.persistence import RunPersistenceInput


class RunPersistenceApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        repository_factory: Callable,
        persist_result: Callable,
        persist_input: Callable | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.repository_factory = repository_factory
        self.persist_result = persist_result
        self.persist_input = persist_input

    def prepare_repository(self):
        repository = self.repository_factory(artifact_root=self.artifact_root)
        repository.migrate()
        return repository

    def persist_prepared_result(self, repository, result: object, *, profile: str) -> None:
        self.persist_result(
            repository,
            result,
            profile=profile,
            migrate=False,
        )

    def persist_prepared_input(self, repository, input_model: RunPersistenceInput) -> None:
        if self.persist_input is None:
            raise RuntimeError("persist_input is not configured")
        self.persist_input(
            repository,
            input_model,
            migrate=False,
        )

    def persist_result_after_migration(self, result: object, *, profile: str) -> None:
        repository = self.prepare_repository()
        self.persist_prepared_result(repository, result, profile=profile)

    def persist_input_after_migration(self, input_model: RunPersistenceInput) -> None:
        repository = self.prepare_repository()
        self.persist_prepared_input(repository, input_model)


__all__ = ["RunPersistenceApplicationService"]
