from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from quality.citation_checker import CitationCheckResult
from quality.scoring import ReportQualitySummary
from quality.support_matrix import SupportMatrix


class EditorDecision(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EditorReview:
    decision: EditorDecision
    reasons: list[str] = field(default_factory=list)
    quality_score: float | None = None

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "quality_score": self.quality_score,
        }


class EditorGate:
    def review(
        self,
        citation_check: CitationCheckResult,
        support_matrix: SupportMatrix | None = None,
        quality_summary: ReportQualitySummary | None = None,
    ) -> EditorReview:
        reasons = []
        if citation_check.unknown_urls:
            reasons.extend(
                [
                    "report cites URLs outside the evidence bundle",
                    *citation_check.unknown_urls,
                ]
            )
        if citation_check.missing_section_sources:
            reasons.append("report sections missing source citations")
            reasons.extend(
                f"missing section sources: {section_title}"
                for section_title in citation_check.missing_section_sources
            )
        if not citation_check.passed and not citation_check.unknown_urls and not citation_check.missing_section_sources:
            reasons.append("citation check failed")
        if support_matrix and support_matrix.unsupported_sections:
            reasons.append("report sections lack evidence support")
            reasons.extend(
                f"unsupported section: {section.section_title}"
                for section in support_matrix.unsupported_sections
            )
        if quality_summary and quality_summary.duplicate_sections:
            reasons.append("duplicate section content detected")
            reasons.extend(
                f"duplicate section: {title}" for title in quality_summary.duplicate_sections
            )

        if reasons:
            return EditorReview(
                decision=EditorDecision.BLOCKED,
                reasons=reasons,
                quality_score=quality_summary.quality_score if quality_summary else None,
            )
        return EditorReview(
            decision=EditorDecision.PASS,
            quality_score=quality_summary.quality_score if quality_summary else None,
        )
