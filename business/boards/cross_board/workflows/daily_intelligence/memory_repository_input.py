from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class DailyQualityMemoryRepositoryInput:
    repository: IntelligenceMemoryQueryRepository | None

    @classmethod
    def from_recall_service(
        cls,
        recall_service: Any,
    ) -> "DailyQualityMemoryRepositoryInput":
        if recall_service is None:
            return cls(repository=None)
        return cls(repository=getattr(recall_service, "repository", None))


def quality_memory_repository_from_recall_service(
    recall_service: Any,
) -> IntelligenceMemoryQueryRepository | None:
    return DailyQualityMemoryRepositoryInput.from_recall_service(
        recall_service
    ).repository


__all__ = [
    "DailyQualityMemoryRepositoryInput",
    "quality_memory_repository_from_recall_service",
]
