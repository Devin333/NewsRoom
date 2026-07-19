from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import Enum
from typing import Any

from business.foundation.primitives.source_ref import source_url_read_aliases


CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD = 0.75


@dataclass(frozen=True)
class AnalysisLineage:
    source_id: str
    source_item_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
        }


@dataclass(frozen=True)
class AnalysisEvidenceItem:
    evidence_id: str
    source_url: str
    title: str
    summary: str
    confidence: float
    source_id: str
    source_item_id: str | None = None
    source_urls: list[str] = field(default_factory=list)
    publishable: bool = True
    lineage: AnalysisLineage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        urls = list(self.source_urls)
        if self.source_url and self.source_url not in urls:
            urls.insert(0, self.source_url)
        object.__setattr__(self, "source_urls", urls)
        if self.lineage is None:
            object.__setattr__(
                self,
                "lineage",
                AnalysisLineage(source_id=self.source_id or "source", source_item_id=self.source_item_id),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "source_urls": list(self.source_urls),
            "title": self.title,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "publishable": self.publishable,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisEvidenceBundle:
    bundle_id: str
    items: list[AnalysisEvidenceItem]
    source_map: dict[str, list[str]] = field(default_factory=dict)
    missing_information: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_map:
            source_map: dict[str, list[str]] = {}
            for item in self.items:
                for url in item.source_urls:
                    if url:
                        source_map.setdefault(url, []).append(item.evidence_id)
            object.__setattr__(self, "source_map", source_map)

    @property
    def source_urls(self) -> set[str]:
        urls: set[str] = set()
        for item in self.items:
            urls.update(url for url in item.source_urls if url)
            if item.source_url:
                urls.add(item.source_url)
        return urls

    @property
    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}


@dataclass(frozen=True)
class CitationFailureCategory:
    code: str
    count: int
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "count": self.count, "items": list(self.items)}


@dataclass(frozen=True)
class CitationSectionResult:
    section_id: str
    section_title: str
    cited_urls: list[str] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    issue_details: dict[str, list[str]] = field(default_factory=dict)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_title": self.section_title,
            "cited_urls": list(self.cited_urls),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "issue_codes": list(self.issue_codes),
            "issue_details": dict(self.issue_details),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    cited_urls: list[str] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    unknown_urls: list[str] = field(default_factory=list)
    unsupported_urls: list[str] = field(default_factory=list)
    unsupported_evidence_ids: list[str] = field(default_factory=list)
    missing_section_sources: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    rejected_claim_usage: list[str] = field(default_factory=list)
    failure_categories: list[CitationFailureCategory] = field(default_factory=list)
    section_results: list[CitationSectionResult] = field(default_factory=list)
    citation_coverage_score: float = 0.0
    claim_support_score: float = 0.0
    section_source_coverage_score: float = 0.0
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "cited_urls": list(self.cited_urls),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "unknown_urls": list(self.unknown_urls),
            "unsupported_urls": list(self.unsupported_urls),
            "unsupported_evidence_ids": list(self.unsupported_evidence_ids),
            "missing_section_sources": list(self.missing_section_sources),
            "unsupported_claims": list(self.unsupported_claims),
            "rejected_claim_usage": list(self.rejected_claim_usage),
            "failure_categories": [category.to_dict() for category in self.failure_categories],
            "failure_category_codes": [category.code for category in self.failure_categories],
            "section_results": [section.to_dict() for section in self.section_results],
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "section_source_coverage_score": self.section_source_coverage_score,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClaimSupport:
    claim_id: str
    text: str
    section_id: str
    evidence_ids: list[str] = field(default_factory=list)
    cited_urls: list[str] = field(default_factory=list)
    support_level: str = "unsupported"
    confidence: float = 0.0

    @property
    def supported(self) -> bool:
        return self.support_level in {"accepted", "supported"} and bool(self.evidence_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "section_id": self.section_id,
            "evidence_ids": list(self.evidence_ids),
            "cited_urls": list(self.cited_urls),
            "support_type": "supports" if self.supported else self.support_level,
            "support_level": self.support_level,
            "confidence": self.confidence,
            "severity": "medium",
        }


@dataclass(frozen=True)
class UnsupportedClaim:
    claim_id: str
    text: str
    section_id: str
    section_title: str
    severity: str = "medium"

    def __str__(self) -> str:
        return f"{self.section_title}: {self.text}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class SectionSupport:
    section_id: str
    section_title: str
    cited_urls: list[str]
    cited_evidence_ids: list[str] = field(default_factory=list)
    matched_evidence_ids: list[str] = field(default_factory=list)
    claim_supports: list[ClaimSupport] = field(default_factory=list)
    matched_evidence_confidences: list[float] = field(default_factory=list)
    coverage_score: float = 0.0
    supported: bool = False

    @property
    def claim_ids(self) -> list[str]:
        return [support.claim_id for support in self.claim_supports]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_title": self.section_title,
            "cited_urls": list(self.cited_urls),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "matched_evidence_ids": list(self.matched_evidence_ids),
            "claim_ids": self.claim_ids,
            "claim_supports": [support.to_dict() for support in self.claim_supports],
            "matched_evidence_confidences": list(self.matched_evidence_confidences),
            "coverage_score": self.coverage_score,
            "supported": self.supported,
        }


@dataclass(frozen=True)
class SupportMatrix:
    sections: list[SectionSupport] = field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)

    @property
    def unsupported_sections(self) -> list[SectionSupport]:
        return [section for section in self.sections if not section.supported]

    @property
    def coverage_ratio(self) -> float:
        if not self.sections:
            return 0.0
        return round(sum(section.coverage_score for section in self.sections) / len(self.sections), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [section.to_dict() for section in self.sections],
            "section_claim_evidence_map": {
                section.section_id: {
                    support.claim_id: list(support.evidence_ids)
                    for support in section.claim_supports
                }
                for section in self.sections
            },
            "coverage_ratio": self.coverage_ratio,
            "supported_claim_count": sum(
                1 for section in self.sections for support in section.claim_supports if support.supported
            ),
            "unsupported_claim_count": len(self.unsupported_claims),
            "rejected_claim_usage_count": 0,
            "unsupported_sections": [section.section_title for section in self.unsupported_sections],
            "unsupported_claims": [claim.to_dict() for claim in self.unsupported_claims],
            "rejected_claim_usage": [],
            "accepted_claim_ids": [],
            "rejected_claim_ids": [],
            "uncertain_claim_ids": [],
            "high_severity_unsupported_claims": [],
        }


@dataclass(frozen=True)
class ReportQualitySummary:
    quality_score: float
    support_coverage: float
    citation_passed: bool
    citation_coverage_score: float
    claim_support_score: float
    evidence_alignment_score: float
    source_reliability_score: float
    passed: bool
    decision: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "overall_score": self.quality_score,
            "support_coverage": self.support_coverage,
            "citation_passed": self.citation_passed,
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "evidence_alignment_score": self.evidence_alignment_score,
            "source_reliability_score": self.source_reliability_score,
            "freshness_score": 1.0,
            "readability_score": 1.0,
            "duplication_score": 1.0,
            "uncertainty_handling_score": 1.0,
            "accepted_claims_count": 0,
            "rejected_claims_count": 0,
            "uncertain_claims_count": 0,
            "unsupported_claims_count": 0,
            "high_severity_unsupported_claims_count": 0,
            "passed": self.passed,
            "decision": self.decision,
            "duplicate_sections": [],
            "reasons": list(self.reasons),
        }


class EditorDecision(str, Enum):
    PASS = "pass"
    REWRITE_REQUIRED = "rewrite_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EditorReview:
    decision: EditorDecision
    reasons: list[str] = field(default_factory=list)
    quality_score: float | None = None
    citation_score: float = 0.0
    evidence_alignment_score: float = 0.0
    unsupported_claims: list[str] = field(default_factory=list)
    hallucination_risks: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "required_changes": [],
            "quality_score": self.quality_score,
            "citation_score": self.citation_score,
            "evidence_alignment_score": self.evidence_alignment_score,
            "readability_score": 1.0,
            "duplication_score": 1.0,
            "unsupported_claims": list(self.unsupported_claims),
            "hallucination_risks": list(self.hallucination_risks),
            "duplicate_points": [],
            "missing_sections": list(self.missing_sections),
            "rewrite_instructions": [],
            "block_reasons": list(self.reasons) if self.decision == EditorDecision.BLOCKED else [],
            "final_notes": "quality gate passed" if self.decision == EditorDecision.PASS else "blocked by evidence or citation boundary",
            "reviewed_by_agent_id": "business.analysis.quality.rule",
            "reviewed_at": self.reviewed_at.isoformat().replace("+00:00", "Z"),
        }


def citation_check(report: dict[str, Any], evidence_bundle: AnalysisEvidenceBundle) -> CitationCheckResult:
    support_matrix = support_matrix_for(report, evidence_bundle)
    cited_urls = sorted(_collect_cited_urls(report))
    known_url_aliases = _source_url_alias_index(evidence_bundle.source_urls)
    publishable_url_aliases = _source_url_alias_index(
        url
        for item in evidence_bundle.items
        if item.publishable
        for url in item.source_urls
        if url
    )
    unknown_urls = sorted(
        url for url in cited_urls if not _source_url_matches(url, known_url_aliases)
    )
    unsupported_urls = sorted(
        url for url in cited_urls
        if _source_url_matches(url, known_url_aliases)
        and not _source_url_matches(url, publishable_url_aliases)
    )
    missing_section_sources = _missing_section_sources(report)
    unsupported_claims = [str(claim) for claim in support_matrix.unsupported_claims]
    citation_coverage = _citation_coverage_score(report, missing_section_sources)
    claim_support = _claim_support_score(report, unsupported_claims)
    section_results = _section_results(
        report,
        unknown_urls=unknown_urls,
        unsupported_urls=unsupported_urls,
        missing_section_sources=missing_section_sources,
        support_matrix=support_matrix,
    )
    failure_categories = _failure_categories(
        unknown_urls=unknown_urls,
        unsupported_urls=unsupported_urls,
        missing_section_sources=missing_section_sources,
        unsupported_claims=unsupported_claims,
        section_results=section_results,
    )
    passed = not (unknown_urls or unsupported_urls or missing_section_sources or unsupported_claims)
    return CitationCheckResult(
        passed=passed,
        cited_urls=cited_urls,
        unknown_urls=unknown_urls,
        unsupported_urls=unsupported_urls,
        missing_section_sources=missing_section_sources,
        unsupported_claims=unsupported_claims,
        failure_categories=failure_categories,
        section_results=section_results,
        citation_coverage_score=citation_coverage,
        claim_support_score=claim_support,
        section_source_coverage_score=citation_coverage,
        metadata={"evidence_bundle_id": evidence_bundle.bundle_id, "support_matrix": support_matrix.to_dict()},
    )


def support_matrix_for(report: dict[str, Any], evidence_bundle: AnalysisEvidenceBundle) -> SupportMatrix:
    evidence_by_url = {
        url: item
        for item in evidence_bundle.items
        for url in (item.source_urls or ([item.source_url] if item.source_url else []))
        if url
    }
    sections: list[SectionSupport] = []
    unsupported_claims: list[UnsupportedClaim] = []
    for index, section in enumerate(report.get("sections", [])):
        section_id = _section_id(section, index)
        section_title = str(section.get("title", "Untitled"))
        cited_urls = _section_sources(section)
        candidate_items = _stable_items([evidence_by_url[url] for url in cited_urls if url in evidence_by_url])
        claims = [] if _is_operational_source_note(section_title, str(section.get("content", ""))) else _section_claims(section)
        supports: list[ClaimSupport] = []
        for claim_index, claim in enumerate(claims):
            matched_items = [item for item in candidate_items if _claim_supported_by_evidence(claim, item)]
            support_level = "supported" if matched_items else "unsupported"
            claim_id = f"{section_id}:claim:{claim_index + 1}"
            support = ClaimSupport(
                claim_id=claim_id,
                text=claim,
                section_id=section_id,
                evidence_ids=[item.evidence_id for item in matched_items],
                cited_urls=cited_urls,
                support_level=support_level,
                confidence=round(max([item.confidence for item in matched_items], default=0.0), 4),
            )
            supports.append(support)
            if not support.supported:
                unsupported_claims.append(
                    UnsupportedClaim(
                        claim_id=claim_id,
                        text=claim,
                        section_id=section_id,
                        section_title=section_title,
                    )
                )
        matched_ids = _stable_strs([
            *(item.evidence_id for item in candidate_items),
            *(evidence_id for support in supports for evidence_id in support.evidence_ids),
        ])
        coverage_score = (
            round(sum(1 for support in supports if support.supported) / len(supports), 4)
            if supports
            else (1.0 if matched_ids else 0.0)
        )
        sections.append(
            SectionSupport(
                section_id=section_id,
                section_title=section_title,
                cited_urls=cited_urls,
                matched_evidence_ids=matched_ids,
                claim_supports=supports,
                matched_evidence_confidences=[item.confidence for item in candidate_items],
                coverage_score=coverage_score,
                supported=bool(matched_ids) and coverage_score >= 1.0,
            )
        )
    return SupportMatrix(sections=sections, unsupported_claims=unsupported_claims)


def quality_score(report: dict[str, Any], check: CitationCheckResult, matrix: SupportMatrix) -> ReportQualitySummary:
    score = 1.0
    reasons: list[str] = []
    if not check.passed:
        score -= 0.4
        reasons.append("citation check failed")
    coverage = matrix.coverage_ratio
    if coverage < 1.0:
        score -= (1.0 - coverage) * 0.4
        reasons.append("one or more sections lack evidence support")
    score = round(max(0.0, min(1.0, score)), 4)
    evidence_alignment = round((coverage + check.claim_support_score) / 2, 4)
    source_reliability = _source_reliability_score(matrix)
    decision = "pass" if check.passed and score >= 0.8 else ("rewrite_required" if score >= 0.5 else "blocked")
    return ReportQualitySummary(
        quality_score=score,
        support_coverage=round(coverage, 4),
        citation_passed=check.passed,
        citation_coverage_score=check.citation_coverage_score,
        claim_support_score=check.claim_support_score,
        evidence_alignment_score=evidence_alignment,
        source_reliability_score=source_reliability,
        passed=decision == "pass",
        decision=decision,
        reasons=reasons,
    )


def editor_review(check: CitationCheckResult, matrix: SupportMatrix, summary: ReportQualitySummary) -> EditorReview:
    reasons: list[str] = []
    risks: list[str] = []
    if check.unknown_urls:
        reasons.append("report cites URLs outside the evidence bundle")
        reasons.extend(check.unknown_urls)
        risks.extend(check.unknown_urls)
    if check.unsupported_urls:
        reasons.append("report cites non-publishable evidence URLs")
        reasons.extend(check.unsupported_urls)
        risks.extend(check.unsupported_urls)
    if check.missing_section_sources:
        reasons.append("report sections missing source citations")
        reasons.extend(f"missing section sources: {title}" for title in check.missing_section_sources)
    evidence_empty_sections = [section for section in matrix.unsupported_sections if not section.matched_evidence_ids]
    if evidence_empty_sections:
        reasons.append("report sections lack evidence support")
        reasons.extend(f"unsupported section: {section.section_title}" for section in evidence_empty_sections)
    if check.unsupported_claims:
        risks.extend(check.unsupported_claims)
    if reasons:
        return EditorReview(
            decision=EditorDecision.BLOCKED,
            reasons=reasons,
            quality_score=summary.quality_score,
            citation_score=check.citation_coverage_score,
            evidence_alignment_score=summary.evidence_alignment_score,
            unsupported_claims=check.unsupported_claims,
            hallucination_risks=risks,
            missing_sections=check.missing_section_sources,
        )
    return EditorReview(
        decision=EditorDecision.PASS,
        reasons=["coverage threshold met and no rejected or high-severity unsupported usage"],
        quality_score=summary.quality_score,
        citation_score=check.citation_coverage_score,
        evidence_alignment_score=summary.evidence_alignment_score,
    )


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _collect_cited_urls(value: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_url", "url"} and isinstance(item, str):
                urls.add(item)
            elif key in {"source_urls", "sources"} and isinstance(item, list):
                urls.update(url for url in item if isinstance(url, str))
            else:
                urls.update(_collect_cited_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.update(_collect_cited_urls(item))
    return urls


def _section_sources(section: dict[str, Any]) -> list[str]:
    sources = section.get("sources") or section.get("source_urls") or []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, str)]
    return []


def _missing_section_sources(report: dict[str, Any]) -> list[str]:
    missing = []
    for section in report.get("sections", []):
        if not _section_sources(section):
            missing.append(str(section.get("title", "Untitled")))
    return missing


def _citation_coverage_score(report: dict[str, Any], missing_section_sources: list[str]) -> float:
    sections = report.get("sections", [])
    if not sections:
        return 0.0
    return round((len(sections) - len(missing_section_sources)) / len(sections), 4)


def _claim_support_score(report: dict[str, Any], unsupported_claims: list[str]) -> float:
    claim_count = sum(len(_section_claims(section)) for section in report.get("sections", []))
    if claim_count == 0:
        return 1.0
    return round(max(0, claim_count - len(unsupported_claims)) / claim_count, 4)


def _section_results(
    report: dict[str, Any],
    *,
    unknown_urls: list[str],
    unsupported_urls: list[str],
    missing_section_sources: list[str],
    support_matrix: SupportMatrix,
) -> list[CitationSectionResult]:
    unknown_aliases = _source_url_alias_index(unknown_urls)
    unsupported_aliases = _source_url_alias_index(unsupported_urls)
    missing_titles = set(missing_section_sources)
    unsupported_by_section: dict[str, list[str]] = {}
    for claim in support_matrix.unsupported_claims:
        unsupported_by_section.setdefault(claim.section_id, []).append(str(claim))
    results: list[CitationSectionResult] = []
    for index, section in enumerate(report.get("sections", [])):
        section_id = _section_id(section, index)
        title = str(section.get("title", "Untitled"))
        urls = _section_sources(section)
        issue_codes: list[str] = []
        details: dict[str, list[str]] = {}
        section_unknown = [url for url in urls if _source_url_matches(url, unknown_aliases)]
        if section_unknown:
            issue_codes.append("unknown_urls")
            details["unknown_urls"] = section_unknown
        section_unsupported = [
            url for url in urls if _source_url_matches(url, unsupported_aliases)
        ]
        if section_unsupported:
            issue_codes.append("unsupported_urls")
            details["unsupported_urls"] = section_unsupported
        if title in missing_titles:
            issue_codes.append("missing_section_sources")
            details["missing_section_sources"] = [title]
        if unsupported_by_section.get(section_id):
            issue_codes.append("unsupported_claims")
            details["unsupported_claims"] = unsupported_by_section[section_id]
        results.append(
            CitationSectionResult(
                section_id=section_id,
                section_title=title,
                cited_urls=urls,
                issue_codes=_stable_strs(issue_codes),
                issue_details=details,
                passed=not issue_codes,
            )
        )
    return results


def _failure_categories(
    *,
    unknown_urls: list[str],
    unsupported_urls: list[str],
    missing_section_sources: list[str],
    unsupported_claims: list[str],
    section_results: list[CitationSectionResult],
) -> list[CitationFailureCategory]:
    categories: list[CitationFailureCategory] = []
    if unknown_urls:
        categories.append(CitationFailureCategory("unknown_urls", len(unknown_urls), list(unknown_urls)))
    if unsupported_urls:
        categories.append(CitationFailureCategory("unsupported_urls", len(unsupported_urls), list(unsupported_urls)))
    if missing_section_sources:
        categories.append(CitationFailureCategory("missing_section_sources", len(missing_section_sources), list(missing_section_sources)))
    if unsupported_claims:
        categories.append(CitationFailureCategory("unsupported_claims", len(unsupported_claims), list(unsupported_claims)))
    failing = [section.section_id for section in section_results if not section.passed]
    if failing:
        categories.append(CitationFailureCategory("failing_sections", len(failing), failing))
    return categories


def _section_claims(section: dict[str, Any]) -> list[str]:
    content = str(section.get("content", "")).strip()
    candidates = _split_claim_sentences(content) if content else []
    bullets = section.get("bullets") or []
    if isinstance(bullets, list):
        candidates.extend(str(bullet).strip() for bullet in bullets if str(bullet).strip())
    return [claim for claim in candidates if len(_tokens(claim)) >= 2]


def _split_claim_sentences(content: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", content).strip()
    sentences = [item.strip(" -") for item in re.split(r"(?<=[.!?])\s+|[\r\n]+", normalized) if item.strip(" -")]
    return sentences or [normalized]


def _claim_supported_by_evidence(claim: str, item: AnalysisEvidenceItem) -> bool:
    evidence_text = f"{item.title} {item.summary}"
    if normalize_text(claim) in normalize_text(evidence_text):
        return True
    return _token_overlap(claim, evidence_text) >= CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD


def _source_reliability_score(matrix: SupportMatrix) -> float:
    confidences = [confidence for section in matrix.sections for confidence in section.matched_evidence_confidences]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)


def _section_id(section: dict[str, Any], section_index: int) -> str:
    section_id = section.get("section_id") or section.get("id")
    if section_id:
        return str(section_id)
    slug = re.sub(r"[^a-z0-9]+", "_", str(section.get("title", "")).casefold()).strip("_")
    return slug or f"section_{section_index + 1}"


def _is_operational_source_note(title: str, content: str) -> bool:
    title_normalized = normalize_text(title)
    content_normalized = normalize_text(content)
    return title_normalized in {"source notes", "sources", "methodology"} or content_normalized.startswith("built from ")


def _source_url_alias_index(urls: Iterable[str]) -> set[str]:
    aliases: set[str] = set()
    for url in urls:
        aliases.update(source_url_read_aliases(url))
    return aliases


def _source_url_matches(url: str, aliases: set[str]) -> bool:
    return not aliases.isdisjoint(source_url_read_aliases(url))


def _stable_items(items: list[AnalysisEvidenceItem]) -> list[AnalysisEvidenceItem]:
    seen: set[str] = set()
    result: list[AnalysisEvidenceItem] = []
    for item in items:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        result.append(item)
    return result


def _stable_strs(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in _STOPWORDS
    }


_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "the",
    "that",
    "this",
    "with",
    "without",
}
