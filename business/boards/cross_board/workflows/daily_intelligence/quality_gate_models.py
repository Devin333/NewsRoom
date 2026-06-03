from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.layers.analysis.quality import EditorReview, RewritePolicy
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository


@dataclass(frozen=True)
class DailyQualityGateInput:
    report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None = None
    historian_context: dict[str, Any] | None = None
    memory_repository: IntelligenceMemoryQueryRepository | None = None


@dataclass(frozen=True)
class QualityGateContext:
    report_draft: dict[str, Any]
    evidence_bundle: Any
    verified_findings: Any
    quality_events: list[Any]
    memory_context: dict[str, Any] | None
    historian_context: dict[str, Any] | None
    memory_quality_result: dict[str, Any]


@dataclass(frozen=True)
class QualityGateEvaluation:
    citation_check: Any
    support_matrix: Any
    quality_summary: Any
    review: EditorReview
    rewrite_policy: RewritePolicy
    final_report_draft: dict[str, Any]
    rewritten_report_draft: dict[str, Any] | None
    rewrite_attempts: int
    human_review_request: Any | None
    human_review_required: bool


__all__ = [
    "DailyQualityGateInput",
    "QualityGateContext",
    "QualityGateEvaluation",
]
