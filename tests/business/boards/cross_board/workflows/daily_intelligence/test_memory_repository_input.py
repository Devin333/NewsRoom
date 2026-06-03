from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.memory_repository_input import (
    DailyQualityMemoryRepositoryInput,
    quality_memory_repository_from_recall_service,
)


def test_quality_memory_repository_input_projects_recall_service_repository() -> None:
    repository = object()

    projected = DailyQualityMemoryRepositoryInput.from_recall_service(
        _RecallService(repository=repository)
    )

    assert projected.repository is repository
    assert (
        quality_memory_repository_from_recall_service(
            _RecallService(repository=repository)
        )
        is repository
    )


def test_quality_memory_repository_input_handles_missing_recall_service() -> None:
    assert DailyQualityMemoryRepositoryInput.from_recall_service(None).repository is None
    assert quality_memory_repository_from_recall_service(None) is None


@dataclass(frozen=True)
class _RecallService:
    repository: object
