from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.memory.intelligence_context import IntelligenceMemoryContext


class ReportMemoryRecallService(Protocol):
    def recall_for_topic(self, topic: str, *, limit: int = 8) -> IntelligenceMemoryContext: ...


@dataclass(frozen=True)
class ReportMemoryContextRequest:
    topic: str
    run_id: str | None = None
    entity_ids: list[str] | None = None
    limit: int = 8


@dataclass(frozen=True)
class ReportMemoryContextResult:
    topic: str
    context: IntelligenceMemoryContext
    prompt_context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "context": self.context.to_dict(),
            "prompt_context": self.prompt_context,
        }


class ReportMemoryContextService:
    def __init__(self, recall_service: ReportMemoryRecallService) -> None:
        self.recall_service = recall_service

    def build_context(self, request: ReportMemoryContextRequest) -> ReportMemoryContextResult:
        context = self.recall_service.recall_for_topic(request.topic, limit=request.limit)
        return ReportMemoryContextResult(
            topic=request.topic,
            context=context,
            prompt_context=context.to_prompt_context(limit=request.limit),
        )


__all__ = [
    "ReportMemoryContextRequest",
    "ReportMemoryContextResult",
    "ReportMemoryContextService",
    "ReportMemoryRecallService",
]
