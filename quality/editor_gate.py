from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from quality.citation_checker import CitationCheckResult
from quality.scoring import ReportQualitySummary
from quality.support_matrix import SupportMatrix


class EditorDecision(str, Enum):
    PASS = "pass"
    REWRITE_REQUIRED = "rewrite_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RewritePolicy:
    max_rewrite_attempts: int = 1
    include_editor_feedback: bool = True
    include_citation_errors: bool = True
    preserve_evidence_boundary: bool = True
    block_if_rewrite_exhausted: bool = True

    def to_dict(self) -> dict:
        return {
            "max_rewrite_attempts": self.max_rewrite_attempts,
            "include_editor_feedback": self.include_editor_feedback,
            "include_citation_errors": self.include_citation_errors,
            "preserve_evidence_boundary": self.preserve_evidence_boundary,
            "block_if_rewrite_exhausted": self.block_if_rewrite_exhausted,
        }


@dataclass(frozen=True)
class EditorReview:
    decision: EditorDecision
    reasons: list[str] = field(default_factory=list)
    quality_score: float | None = None
    citation_score: float = 0.0
    evidence_alignment_score: float = 0.0
    readability_score: float = 1.0
    duplication_score: float = 1.0
    unsupported_claims: list[str] = field(default_factory=list)
    hallucination_risks: list[str] = field(default_factory=list)
    duplicate_points: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    rewrite_instructions: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)
    final_notes: str | None = None
    reviewed_by_agent_id: str | None = "quality.editor_gate.rule"
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.reasons:
            return
        combined = [*self.block_reasons, *self.rewrite_instructions]
        object.__setattr__(self, "reasons", combined)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "quality_score": self.quality_score,
            "citation_score": self.citation_score,
            "evidence_alignment_score": self.evidence_alignment_score,
            "readability_score": self.readability_score,
            "duplication_score": self.duplication_score,
            "unsupported_claims": list(self.unsupported_claims),
            "hallucination_risks": list(self.hallucination_risks),
            "duplicate_points": list(self.duplicate_points),
            "missing_sections": list(self.missing_sections),
            "rewrite_instructions": list(self.rewrite_instructions),
            "block_reasons": list(self.block_reasons),
            "final_notes": self.final_notes,
            "reviewed_by_agent_id": self.reviewed_by_agent_id,
            "reviewed_at": self.reviewed_at.isoformat().replace("+00:00", "Z"),
        }


class EditorGate:
    def review(
        self,
        citation_check: CitationCheckResult,
        support_matrix: SupportMatrix | None = None,
        quality_summary: ReportQualitySummary | None = None,
        rewrite_policy: RewritePolicy | None = None,
        rewrite_attempts: int = 0,
    ) -> EditorReview:
        policy = rewrite_policy or RewritePolicy()
        block_reasons = []
        rewrite_instructions = []
        hallucination_risks = []

        if citation_check.unsupported_urls:
            block_reasons.extend(
                [
                    "report cites URLs outside the evidence bundle",
                    *citation_check.unsupported_urls,
                ]
            )
            hallucination_risks.extend(citation_check.unsupported_urls)
        if citation_check.rejected_claim_usage:
            block_reasons.append("report uses rejected claims as facts")
            block_reasons.extend(
                f"rejected claim used: {claim}" for claim in citation_check.rejected_claim_usage
            )
        if citation_check.missing_section_sources:
            block_reasons.append("report sections missing source citations")
            block_reasons.extend(
                f"missing section sources: {section_title}"
                for section_title in citation_check.missing_section_sources
            )
        if citation_check.unsupported_claims:
            rewrite_instructions.append("remove or rewrite unsupported report claims")
            rewrite_instructions.extend(
                f"unsupported claim: {claim}" for claim in citation_check.unsupported_claims
            )
            hallucination_risks.extend(citation_check.unsupported_claims)
        if citation_check.notes:
            rewrite_instructions.extend(citation_check.notes)
        if (
            not citation_check.passed
            and not citation_check.unsupported_urls
            and not citation_check.missing_section_sources
            and not citation_check.unsupported_claims
            and not citation_check.rejected_claim_usage
        ):
            rewrite_instructions.append("citation check failed")
        if support_matrix and support_matrix.unsupported_sections:
            block_reasons.append("report sections lack evidence support")
            block_reasons.extend(
                f"unsupported section: {section.section_title}"
                for section in support_matrix.unsupported_sections
            )
        if quality_summary and quality_summary.duplicate_sections:
            rewrite_instructions.append("deduplicate repeated report sections")
            rewrite_instructions.extend(
                f"duplicate section: {title}" for title in quality_summary.duplicate_sections
            )
        if quality_summary and quality_summary.quality_score < 0.8 and not block_reasons:
            rewrite_instructions.append("raise report quality above the publishing threshold")

        exhausted = rewrite_attempts >= policy.max_rewrite_attempts
        if block_reasons:
            return EditorReview(
                decision=EditorDecision.BLOCKED,
                block_reasons=block_reasons,
                quality_score=quality_summary.quality_score if quality_summary else None,
                citation_score=citation_check.citation_coverage_score,
                evidence_alignment_score=(
                    quality_summary.evidence_alignment_score if quality_summary else 0.0
                ),
                readability_score=quality_summary.readability_score if quality_summary else 1.0,
                duplication_score=quality_summary.duplication_score if quality_summary else 1.0,
                unsupported_claims=citation_check.unsupported_claims,
                hallucination_risks=hallucination_risks,
                duplicate_points=quality_summary.duplicate_sections if quality_summary else [],
                missing_sections=citation_check.missing_section_sources,
                final_notes="blocked by evidence or citation boundary",
            )
        if rewrite_instructions:
            if exhausted and policy.block_if_rewrite_exhausted:
                return EditorReview(
                    decision=EditorDecision.BLOCKED,
                    block_reasons=["rewrite attempts exhausted", *rewrite_instructions],
                    quality_score=quality_summary.quality_score if quality_summary else None,
                    citation_score=citation_check.citation_coverage_score,
                    evidence_alignment_score=(
                        quality_summary.evidence_alignment_score if quality_summary else 0.0
                    ),
                    readability_score=quality_summary.readability_score if quality_summary else 1.0,
                    duplication_score=quality_summary.duplication_score if quality_summary else 1.0,
                    unsupported_claims=citation_check.unsupported_claims,
                    hallucination_risks=hallucination_risks,
                    duplicate_points=quality_summary.duplicate_sections if quality_summary else [],
                    missing_sections=citation_check.missing_section_sources,
                    final_notes="blocked after rewrite budget was exhausted",
                )
            return EditorReview(
                decision=EditorDecision.REWRITE_REQUIRED,
                rewrite_instructions=rewrite_instructions,
                quality_score=quality_summary.quality_score if quality_summary else None,
                citation_score=citation_check.citation_coverage_score,
                evidence_alignment_score=(
                    quality_summary.evidence_alignment_score if quality_summary else 0.0
                ),
                readability_score=quality_summary.readability_score if quality_summary else 1.0,
                duplication_score=quality_summary.duplication_score if quality_summary else 1.0,
                unsupported_claims=citation_check.unsupported_claims,
                hallucination_risks=hallucination_risks,
                duplicate_points=quality_summary.duplicate_sections if quality_summary else [],
                missing_sections=citation_check.missing_section_sources,
                final_notes="rewrite required before finalization",
            )
        return EditorReview(
            decision=EditorDecision.PASS,
            quality_score=quality_summary.quality_score if quality_summary else None,
            citation_score=citation_check.citation_coverage_score,
            evidence_alignment_score=quality_summary.evidence_alignment_score if quality_summary else 0.0,
            readability_score=quality_summary.readability_score if quality_summary else 1.0,
            duplication_score=quality_summary.duplication_score if quality_summary else 1.0,
            final_notes="quality gate passed",
        )
