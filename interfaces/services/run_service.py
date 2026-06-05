from __future__ import annotations

from pathlib import Path
from typing import Any

from interfaces.services.run_persistence_service import RunPersistenceApplicationService
from infrastructure.storage.persistence import persist_run_input, persist_run_result, repository_from_env


class RunApplicationService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        memory_ingestion_service: Any | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.memory_ingestion_service = memory_ingestion_service

    def _persistence_service(self) -> RunPersistenceApplicationService:
        return RunPersistenceApplicationService(
            artifact_root=self.artifact_root,
            repository_factory=repository_from_env,
            persist_result=persist_run_result,
            persist_input=persist_run_input,
        )


__all__ = [
    "RunApplicationService",
    "RunPersistenceApplicationService",
    "persist_run_input",
    "persist_run_result",
    "repository_from_env",
]
