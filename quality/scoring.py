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
    overall_score: float | None = None
    citation_coverage_score: float = 0.0
    claim_support_score: float = 0.0
    evidence_alignment_score: float = 0.0
    source_reliability_score: float = 0.0
    freshness_score: float = 1.0
    readability_score: float = 1.0
    duplication_score: float = 1.0
    uncertainty_handling_score: float = 1.0
    passed: bool = False
    decision: str = "blocked"
    duplicate_sections: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "overall_score": self.quality_score if self.overall_score is None else self.overall_score,
            "support_coverage": self.support_coverage,
            "citation_passed": self.citation_passed,
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "evidence_alignment_score": self.evidence_alignment_score,
            "source_reliability_score": self.source_reliability_score,
            "freshness_score": self.freshness_score,
            "readability_score": self.readability_score,
            "duplication_score": self.duplication_score,
            "uncertainty_handling_score": self.uncertainty_handling_score,
            "passed": self.passed,
            "decision": self.decision,
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
        readability_score = _readability_score(report)
        if readability_score < 0.75:
            score -= 0.1
            reasons.append("report readability is below threshold")
        score = round(max(0.0, min(1.0, score)), 4)
        claim_support_score = citation_check.claim_support_score
        evidence_alignment_score = round((coverage + claim_support_score) / 2, 4)
        source_reliability_score = _source_reliability_score(support_matrix)
        duplication_score = 1.0 if not duplicate_sections else max(0.0, round(1.0 - 0.2 * len(duplicate_sections), 4))
        uncertainty_handling_score = 0.8 if citation_check.notes else 1.0
        decision = _quality_decision(score, citation_check.passed)
        return ReportQualitySummary(
            quality_score=score,
            overall_score=score,
            support_coverage=round(coverage, 4),
            citation_passed=citation_check.passed,
            citation_coverage_score=citation_check.citation_coverage_score,
            claim_support_score=claim_support_score,
            evidence_alignment_score=evidence_alignment_score,
            source_reliability_score=source_reliability_score,
            freshness_score=1.0,
            readability_score=readability_score,
            duplication_score=duplication_score,
            uncertainty_handling_score=uncertainty_handling_score,
            passed=decision == "pass",
            decision=decision,
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


def _readability_score(report: dict) -> float:
    contents = [str(section.get("content", "")) for section in report.get("sections", [])]
    text = " ".join(contents).strip()
    if not text:
        return 0.0
    words = re.findall(r"\w+", text)
    if not words:
        return 0.0
    avg_sentence_words = len(words) / max(1, len(re.findall(r"[.!?]", text)) or 1)
    if avg_sentence_words <= 35:
        return 1.0
    if avg_sentence_words <= 55:
        return 0.8
    return 0.6


def _source_reliability_score(support_matrix: SupportMatrix) -> float:
    confidences = [
        confidence
        for section in support_matrix.sections
        for confidence in section.matched_evidence_confidences
    ]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)


def _quality_decision(score: float, citation_passed: bool) -> str:
    if citation_passed and score >= 0.8:
        return "pass"
    if score >= 0.5:
        return "rewrite_required"
    return "blocked"
