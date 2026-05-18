from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from quality.support_matrix import SupportMatrix, SupportMatrixBuilder


CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD = 0.75


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    cited_urls: list[str] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    unsupported_urls: list[str] = field(default_factory=list)
    unsupported_evidence_ids: list[str] = field(default_factory=list)
    missing_section_sources: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    rejected_claim_usage: list[str] = field(default_factory=list)
    citation_coverage_score: float = 0.0
    claim_support_score: float = 0.0
    section_source_coverage_score: float = 0.0
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def unknown_urls(self) -> list[str]:
        return self.unsupported_urls

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "cited_urls": list(self.cited_urls),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "unsupported_urls": list(self.unsupported_urls),
            "unsupported_evidence_ids": list(self.unsupported_evidence_ids),
            "unknown_urls": list(self.unsupported_urls),
            "missing_section_sources": list(self.missing_section_sources),
            "unsupported_claims": list(self.unsupported_claims),
            "rejected_claim_usage": list(self.rejected_claim_usage),
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "section_source_coverage_score": self.section_source_coverage_score,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }


class CitationChecker:
    def check(
        self,
        report: dict,
        evidence_bundle: EvidenceBundle,
        verified_findings: VerifiedFindings | None = None,
    ) -> CitationCheckResult:
        cited_urls = sorted(_collect_cited_urls(report))
        cited_evidence_ids = sorted(_collect_cited_evidence_ids(report))
        allowed_urls = evidence_bundle.source_urls
        allowed_evidence_ids = evidence_bundle.evidence_ids
        unsupported_urls = sorted(url for url in cited_urls if url not in allowed_urls)
        unsupported_evidence_ids = sorted(
            evidence_id for evidence_id in cited_evidence_ids if evidence_id not in allowed_evidence_ids
        )
        missing_section_sources = _missing_section_sources(report)
        support_matrix = SupportMatrixBuilder().build(report, evidence_bundle, verified_findings)
        unsupported_claims = [str(claim) for claim in support_matrix.unsupported_claims]
        rejected_claim_usage = [
            usage.text for usage in support_matrix.rejected_claim_usage
        ]
        uncertain_notes = _uncertain_claim_notes(report, verified_findings)
        notes = [*uncertain_notes]
        section_source_coverage_score = _citation_coverage_score(report, missing_section_sources)
        claim_support_score = _claim_support_score(report, unsupported_claims)
        return CitationCheckResult(
            passed=not (
                unsupported_urls
                or unsupported_evidence_ids
                or missing_section_sources
                or unsupported_claims
                or rejected_claim_usage
            ),
            cited_urls=cited_urls,
            cited_evidence_ids=cited_evidence_ids,
            unsupported_urls=unsupported_urls,
            unsupported_evidence_ids=unsupported_evidence_ids,
            missing_section_sources=missing_section_sources,
            unsupported_claims=unsupported_claims,
            rejected_claim_usage=rejected_claim_usage,
            citation_coverage_score=section_source_coverage_score,
            claim_support_score=claim_support_score,
            section_source_coverage_score=section_source_coverage_score,
            notes=notes,
            metadata={
                "evidence_bundle_id": evidence_bundle.bundle_id,
                "evidence_item_count": len(evidence_bundle.items),
                "verified_claim_count": len(verified_findings.all_claims) if verified_findings else 0,
                "support_matrix": support_matrix.to_dict(),
            },
        )


def _collect_cited_urls(value) -> set[str]:
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


def _collect_cited_evidence_ids(value) -> set[str]:
    evidence_ids: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidence_id"} and isinstance(item, str):
                evidence_ids.add(item)
            elif key in {"evidence_ids", "citation_evidence_ids"} and isinstance(item, list):
                evidence_ids.update(str(value) for value in item if value is not None)
            elif key == "citations" and isinstance(item, list):
                for citation in item:
                    if isinstance(citation, str) and citation.startswith("ev_"):
                        evidence_ids.add(citation)
                    elif isinstance(citation, dict) and citation.get("evidence_id"):
                        evidence_ids.add(str(citation["evidence_id"]))
            else:
                evidence_ids.update(_collect_cited_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            evidence_ids.update(_collect_cited_evidence_ids(item))
    return evidence_ids


def _missing_section_sources(report: dict) -> list[str]:
    missing = []
    for section in report.get("sections", []):
        if not _section_sources(section) and not _section_evidence_ids(section):
            missing.append(str(section.get("title", "Untitled")))
    return missing


def _citation_coverage_score(report: dict, missing_section_sources: list[str]) -> float:
    sections = report.get("sections", [])
    if not sections:
        return 0.0
    covered_count = max(0, len(sections) - len(missing_section_sources))
    return round(covered_count / len(sections), 4)


def _section_sources(section: dict) -> list[str]:
    sources = section.get("sources") or section.get("source_urls") or []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, str)]
    return []


def _section_evidence_ids(section: dict) -> list[str]:
    evidence_ids = section.get("evidence_ids") or []
    citations = section.get("citations") or []
    values: list[Any] = []
    if isinstance(evidence_ids, list):
        values.extend(evidence_ids)
    elif isinstance(evidence_ids, str):
        values.append(evidence_ids)
    if isinstance(citations, list):
        values.extend(
            citation.get("evidence_id")
            if isinstance(citation, dict)
            else citation
            for citation in citations
        )
    elif isinstance(citations, str):
        values.append(citations)
    return [str(value) for value in values if value is not None and str(value)]


def _unsupported_claims(report: dict, evidence_bundle: EvidenceBundle) -> list[str]:
    evidence_by_url = {item.source_url: item for item in evidence_bundle.items}
    unsupported = []
    for section in report.get("sections", []):
        section_title = str(section.get("title", "Untitled"))
        if _is_operational_source_note(section_title, str(section.get("content", ""))):
            continue
        cited_items = [
            evidence_by_url[url]
            for url in _section_sources(section)
            if url in evidence_by_url
        ]
        for claim in _section_claims(section):
            if not cited_items:
                unsupported.append(f"{section_title}: {claim}")
                continue
            if not any(_claim_supported_by_evidence(claim, item) for item in cited_items):
                unsupported.append(f"{section_title}: {claim}")
    return unsupported


def _rejected_claim_usage(
    report: dict,
    verified_findings: VerifiedFindings | None,
) -> list[str]:
    if verified_findings is None:
        return []
    report_text = _normalize(_report_text(report))
    usages = []
    for claim in verified_findings.rejected_claims:
        normalized_claim = _normalize(claim.claim)
        if not normalized_claim:
            continue
        if normalized_claim in report_text or _token_overlap(claim.claim, report_text) >= 0.75:
            usages.append(claim.claim)
    return usages


def _uncertain_claim_notes(
    report: dict,
    verified_findings: VerifiedFindings | None,
) -> list[str]:
    if verified_findings is None:
        return []
    report_text = _normalize(_report_text(report))
    if not report_text:
        return []
    notes = []
    uncertainty_markers = {"uncertain", "unconfirmed", "may", "could", "preliminary", "reported"}
    for claim in verified_findings.uncertain_claims:
        normalized_claim = _normalize(claim.claim)
        if not normalized_claim or normalized_claim not in report_text:
            continue
        if not any(marker in report_text for marker in uncertainty_markers):
            notes.append(f"uncertain claim not explicitly marked: {claim.claim}")
    return notes


def _claim_support_score(report: dict, unsupported_claims: list[str]) -> float:
    claim_count = sum(len(_section_claims(section)) for section in report.get("sections", []))
    if claim_count == 0:
        return 1.0
    supported_count = max(0, claim_count - len(unsupported_claims))
    return round(supported_count / claim_count, 4)


def _section_claims(section: dict) -> list[str]:
    content = str(section.get("content", "")).strip()
    bullets = section.get("bullets") or []
    candidates = []
    if content:
        candidates.extend(_split_claim_sentences(content))
    if isinstance(bullets, list):
        candidates.extend(str(bullet).strip() for bullet in bullets if str(bullet).strip())
    return [claim for claim in candidates if len(_tokens(claim)) >= 2]


def _split_claim_sentences(content: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return []
    sentences = [
        sentence.strip(" -")
        for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", normalized)
        if sentence.strip(" -")
    ]
    return sentences or [normalized]


def _claim_supported_by_evidence(claim: str, item: EvidenceItem) -> bool:
    evidence_text = f"{item.title} {item.summary}"
    atomic_claims = _atomic_claims(claim)
    if len(atomic_claims) > 1:
        return all(_single_claim_supported_by_evidence(part, evidence_text) for part in atomic_claims)
    return _single_claim_supported_by_evidence(claim, evidence_text)


def _single_claim_supported_by_evidence(claim: str, evidence_text: str) -> bool:
    if _normalize(claim) in _normalize(evidence_text):
        return True
    return _token_overlap(claim, evidence_text) >= CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD


def _atomic_claims(claim: str) -> list[str]:
    parts = [
        part.strip(" -.,;:")
        for part in re.split(r"\s*;\s*|\s+\b(?:and|but|while|whereas)\b\s+", claim)
    ]
    return [part for part in parts if len(_tokens(part)) >= 1]


def _report_text(report: dict) -> str:
    parts = [str(report.get("title", ""))]
    for section in report.get("sections", []):
        parts.append(str(section.get("title", "")))
        parts.append(str(section.get("content", "")))
        bullets = section.get("bullets") or []
        if isinstance(bullets, list):
            parts.extend(str(bullet) for bullet in bullets)
    return " ".join(parts)


def _is_operational_source_note(title: str, content: str) -> bool:
    title_normalized = _normalize(title)
    content_normalized = _normalize(content)
    if title_normalized in {"source notes", "sources", "methodology"}:
        return True
    return content_normalized.startswith("built from ") or content_normalized.startswith(
        "source collection was partial"
    )


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    if not left_tokens:
        return 0.0
    right_tokens = _tokens(right)
    if not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


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
