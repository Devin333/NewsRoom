from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.memory_quality import (
    DailyMemoryQualityService,
)
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class DailyQualityContextProjectionInput:
    report_draft: dict[str, Any]
    memory_context: dict[str, Any] | None = None
    historian_context: dict[str, Any] | None = None
    memory_repository: IntelligenceMemoryQueryRepository | None = None


@dataclass(frozen=True)
class DailyQualityContextProjection:
    memory_context: dict[str, Any] | None
    historian_context: dict[str, Any] | None
    memory_quality_result: dict[str, Any]


class DailyQualityContextProjectionService:
    def __init__(self, *, memory_quality_service: DailyMemoryQualityService | None = None) -> None:
        self.memory_quality_service = memory_quality_service or DailyMemoryQualityService()

    def build(self, payload: DailyQualityContextProjectionInput) -> DailyQualityContextProjection:
        historian_context = _historian_context(
            explicit_historian_context=payload.historian_context,
            report_draft=payload.report_draft,
            memory_context=payload.memory_context,
        )
        memory_quality_result = self.memory_quality_service.evaluate(
            payload.memory_context,
            repository=payload.memory_repository,
        )
        return DailyQualityContextProjection(
            memory_context=payload.memory_context,
            historian_context=historian_context,
            memory_quality_result=_with_historian_quality_metadata(
                memory_quality_result,
                historian_context,
            ),
        )


def _historian_context(
    *,
    explicit_historian_context: dict[str, Any] | None,
    report_draft: dict[str, Any],
    memory_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if explicit_historian_context:
        return dict(explicit_historian_context)
    report_metadata = report_draft.get("metadata") if isinstance(report_draft, dict) else None
    if isinstance(report_metadata, dict) and isinstance(report_metadata.get("historian"), dict):
        return dict(report_metadata["historian"])
    memory_metadata = memory_context.get("metadata") if memory_context else None
    if isinstance(memory_metadata, dict) and isinstance(memory_metadata.get("historian"), dict):
        return dict(memory_metadata["historian"])
    return None


def _with_historian_quality_metadata(
    memory_quality_result: dict[str, Any],
    historian_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not historian_context:
        return memory_quality_result
    payload = dict(memory_quality_result)
    metadata = dict(payload.get("metadata") or {})
    raw_output = historian_context.get("output")
    output = dict(raw_output) if isinstance(raw_output, dict) else {}
    repeated_claims = list(output.get("repeated_claims") or [])
    contradictions = list(output.get("contradictions") or [])
    metadata["historian"] = historian_context
    metadata["historian_repeated_claims"] = repeated_claims
    metadata["historian_contradictions"] = contradictions
    metadata["historian_repeated_claim_count"] = len(repeated_claims)
    metadata["historian_contradiction_count"] = len(contradictions)
    payload["metadata"] = metadata
    return payload


__all__ = [
    "DailyQualityContextProjection",
    "DailyQualityContextProjectionInput",
    "DailyQualityContextProjectionService",
]
