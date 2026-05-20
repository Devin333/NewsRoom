from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from business.layers.analysis.quality.citation_checker import CitationCheckResult
from business.layers.analysis.quality.scoring import ReportQualitySummary
from business.layers.analysis.quality.support_matrix import SupportMatrix


class EditorDecision(str, Enum):
    PASS = "pass"
    REWRITE_REQUIRED = "rewrite_required"
    BLOCKED = "blocked"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class RewriteValidationResult:
    passed: bool
    new_source_urls: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    uncertain_claims_as_fact: list[str] = field(default_factory=list)
    decision: EditorDecision = EditorDecision.PASS

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "new_source_urls": list(self.new_source_urls),
            "unsupported_claims": list(self.unsupported_claims),
            "uncertain_claims_as_fact": list(self.uncertain_claims_as_fact),
            "decision": self.decision.value,
        }


@dataclass(frozen=True)
class RewritePolicy:
    max_rewrite_attempts: int = 1
    include_editor_feedback: bool = True
    include_citation_errors: bool = True
    preserve_evidence_boundary: bool = True
    block_if_rewrite_exhausted: bool = True

    def instructions_for(self, review: EditorReview) -> list[str]:
        instructions = []
        if review.unsupported_claims:
            instructions.extend(
                f"delete or downgrade unsupported claim: {claim}"
                for claim in review.unsupported_claims
            )
        if review.missing_sections:
            instructions.extend(
                f"add citation from existing evidence only: {section}"
                for section in review.missing_sections
            )
        if review.rewrite_instructions:
            instructions.extend(review.rewrite_instructions)
        return _stable(instructions)

    def validate_rewrite(
        self,
        *,
        rewritten_report: dict,
        evidence_bundle: Any,
        verified_findings: Any | None = None,
    ) -> RewriteValidationResult:
        from business.layers.analysis.quality.citation_checker import CitationChecker

        citation_check = CitationChecker().check(
            rewritten_report,
            evidence_bundle,
            verified_findings,
        )
        new_source_urls = list(citation_check.unknown_urls)
        unsupported_source_urls = list(citation_check.unsupported_urls)
        uncertain_as_fact = []
        if verified_findings is not None:
            uncertain_as_fact = _uncertain_claims_as_fact(
                rewritten_report,
                verified_findings.uncertain_claims,
            )
        passed = (
            citation_check.passed
            and not new_source_urls
            and not unsupported_source_urls
            and not citation_check.unsupported_claims
            and not uncertain_as_fact
        )
        return RewriteValidationResult(
            passed=passed,
            new_source_urls=new_source_urls,
            unsupported_claims=list(citation_check.unsupported_claims),
            uncertain_claims_as_fact=uncertain_as_fact,
            decision=EditorDecision.PASS if passed else EditorDecision.BLOCKED,
        )

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
    required_changes: list[str] = field(default_factory=list)
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
    reviewed_by_agent_id: str | None = "business.layers.analysis.quality.editor_gate.rule"
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        combined = [*self.block_reasons, *self.rewrite_instructions, *self.required_changes]
        if not self.reasons:
            object.__setattr__(self, "reasons", combined)
        if not self.required_changes:
            object.__setattr__(self, "required_changes", list(self.rewrite_instructions))

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "required_changes": list(self.required_changes),
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
        report_draft: dict | None = None,
        rewrite_policy: RewritePolicy | None = None,
        rewrite_attempts: int = 0,
    ) -> EditorReview:
        policy = rewrite_policy or RewritePolicy()
        block_reasons = []
        rewrite_instructions = []
        hallucination_risks = []

        support_coverage = support_matrix.coverage_ratio if support_matrix else 1.0
        high_severity_unsupported = [
            claim
            for claim in (support_matrix.unsupported_claims if support_matrix else [])
            if getattr(claim, "severity", "medium") == "high"
        ]

        if citation_check.unknown_urls:
            block_reasons.extend(
                [
                    "report cites URLs outside the evidence bundle",
                    *citation_check.unknown_urls,
                ]
            )
            hallucination_risks.extend(citation_check.unknown_urls)
        if citation_check.unsupported_urls:
            block_reasons.extend(
                [
                    "report cites non-publishable evidence URLs",
                    *citation_check.unsupported_urls,
                ]
            )
            hallucination_risks.extend(citation_check.unsupported_urls)
        if citation_check.unsupported_evidence_ids:
            block_reasons.extend(
                [
                    "report cites evidence IDs outside the evidence bundle",
                    *citation_check.unsupported_evidence_ids,
                ]
            )
            hallucination_risks.extend(citation_check.unsupported_evidence_ids)
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
        if high_severity_unsupported:
            block_reasons.append("high severity unsupported claims cannot be published")
            block_reasons.extend(
                f"high severity unsupported claim: {claim.text}"
                for claim in high_severity_unsupported
            )
        if citation_check.notes:
            rewrite_instructions.extend(citation_check.notes)
        if (
            not citation_check.passed
            and not citation_check.unknown_urls
            and not citation_check.unsupported_urls
            and not citation_check.missing_section_sources
            and not citation_check.unsupported_claims
            and not citation_check.rejected_claim_usage
        ):
            rewrite_instructions.append("citation check failed")
        evidence_empty_sections = [
            section
            for section in (support_matrix.unsupported_sections if support_matrix else [])
            if not section.matched_evidence_ids
        ]
        if evidence_empty_sections:
            block_reasons.append("report sections lack evidence support")
            block_reasons.extend(
                f"unsupported section: {section.section_title}"
                for section in evidence_empty_sections
            )
        if support_matrix and len(support_matrix.unsupported_claims) >= 3:
            block_reasons.append("too many unsupported claims")
        if quality_summary and quality_summary.support_coverage == 0.0:
            block_reasons.append("no evidence supports report sections")
        if quality_summary and quality_summary.duplicate_sections:
            rewrite_instructions.append("deduplicate repeated report sections")
            rewrite_instructions.extend(
                f"duplicate section: {title}" for title in quality_summary.duplicate_sections
            )
        if quality_summary and quality_summary.quality_score < 0.8 and not block_reasons:
            rewrite_instructions.append("raise report quality above the publishing threshold")
        if (
            not block_reasons
            and not rewrite_instructions
            and quality_summary
            and _needs_human_review(report_draft, quality_summary, support_coverage)
        ):
            return EditorReview(
                decision=EditorDecision.HUMAN_REVIEW,
                reasons=["borderline or high-risk report requires quality review"],
                required_changes=["human reviewer must approve, reject, or request rewrite"],
                quality_score=quality_summary.quality_score,
                citation_score=citation_check.citation_coverage_score,
                evidence_alignment_score=quality_summary.evidence_alignment_score,
                readability_score=quality_summary.readability_score,
                duplication_score=quality_summary.duplication_score,
                unsupported_claims=citation_check.unsupported_claims,
                hallucination_risks=hallucination_risks,
                duplicate_points=quality_summary.duplicate_sections,
                missing_sections=citation_check.missing_section_sources,
                final_notes="quality review required before finalization",
            )

        exhausted = rewrite_attempts >= policy.max_rewrite_attempts
        if block_reasons:
            return EditorReview(
                decision=EditorDecision.BLOCKED,
                block_reasons=block_reasons,
                required_changes=["do not publish; create blocked report artifact"],
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
                    required_changes=["do not publish; create blocked report artifact"],
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
                required_changes=policy.instructions_for(
                    EditorReview(
                        decision=EditorDecision.REWRITE_REQUIRED,
                        rewrite_instructions=rewrite_instructions,
                        unsupported_claims=citation_check.unsupported_claims,
                        missing_sections=citation_check.missing_section_sources,
                    )
                ),
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
            reasons=["coverage threshold met and no rejected or high-severity unsupported usage"],
            quality_score=quality_summary.quality_score if quality_summary else None,
            citation_score=citation_check.citation_coverage_score,
            evidence_alignment_score=quality_summary.evidence_alignment_score if quality_summary else 0.0,
            readability_score=quality_summary.readability_score if quality_summary else 1.0,
            duplication_score=quality_summary.duplication_score if quality_summary else 1.0,
            final_notes="quality gate passed",
        )


def _needs_human_review(
    report_draft: dict | None,
    quality_summary: ReportQualitySummary,
    support_coverage: float,
) -> bool:
    if quality_summary.quality_score < 0.85 and support_coverage < 0.95:
        return True
    if not report_draft:
        return False
    text = " ".join(
        [
            str(report_draft.get("title", "")),
            *[
                f"{section.get('title', '')} {section.get('content', '')}"
                for section in report_draft.get("sections", [])
            ],
        ]
    ).casefold()
    high_risk_terms = {"medical", "legal", "security breach", "critical vulnerability", "public safety"}
    return any(term in text for term in high_risk_terms)


def _uncertain_claims_as_fact(report: dict, uncertain_claims: list[Any]) -> list[str]:
    text = " ".join(
        [
            str(report.get("title", "")),
            *[
                f"{section.get('title', '')} {section.get('content', '')}"
                for section in report.get("sections", [])
            ],
        ]
    ).casefold()
    markers = {"uncertain", "unconfirmed", "may", "could", "preliminary", "reported"}
    results = []
    for claim in uncertain_claims:
        claim_text = str(getattr(claim, "claim", ""))
        if claim_text.casefold() in text and not any(marker in text for marker in markers):
            results.append(claim_text)
    return results


def _stable(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
