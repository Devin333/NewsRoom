from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from quality.citation_checker import CitationCheckResult
from quality.support_matrix import SupportMatrix


@dataclass(frozen=True)
class ReportQualitySummary:
    quality_score: float
    support_coverage: float
    citation_passed: bool
    duplicate_sections: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "support_coverage": self.support_coverage,
            "citation_passed": self.citation_passed,
            "duplicate_sections": list(self.duplicate_sections),
            "reasons": list(self.reasons),
        }


class QualityScorer:
    def score(
        self,
        *,
        report: dict,
        citation_check: CitationCheckResult,
        support_matrix: SupportMatrix,
    ) -> ReportQualitySummary:
        duplicate_sections = _duplicate_sections(report)
        score = 1.0
        reasons: list[str] = []
        if not citation_check.passed:
            score -= 0.4
            reasons.append("citation check failed")
        coverage = support_matrix.coverage_ratio
        score -= (1.0 - coverage) * 0.4
        if coverage < 1.0:
            reasons.append("one or more sections lack evidence support")
        if duplicate_sections:
            score -= 0.2
            reasons.append("duplicate section content detected")
        score = round(max(0.0, min(1.0, score)), 4)
        return ReportQualitySummary(
            quality_score=score,
            support_coverage=round(coverage, 4),
            citation_passed=citation_check.passed,
            duplicate_sections=duplicate_sections,
            reasons=reasons,
        )


def _duplicate_sections(report: dict) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for section in report.get("sections", []):
        title = str(section.get("title", "Untitled"))
        content = _normalize(str(section.get("content", "")))
        if not content:
            continue
        if content in seen:
            duplicates.append(title)
        else:
            seen[content] = title
    return duplicates


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
