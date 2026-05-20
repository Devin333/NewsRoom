from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from business.layers.relation.evidence import ClaimExtractor, EvidenceBundle, VerifiedFindings
from business.layers.relation.evidence.models import Claim, EvidenceItem


CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD = 0.75


@dataclass(frozen=True)
class UnsupportedClaim:
    claim_id: str
    text: str
    section_id: str
    section_title: str | None = None
    severity: str = "medium"

    def __str__(self) -> str:
        return f"{self.section_title or self.section_id}: {self.text}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class RejectedClaimUsage:
    claim_id: str
    text: str
    section_id: str
    reason: str | None = None

    def __str__(self) -> str:
        return self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "section_id": self.section_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ClaimSupport:
    claim_id: str
    text: str
    section_id: str
    evidence_ids: list[str] = field(default_factory=list)
    cited_urls: list[str] = field(default_factory=list)
    support_type: str = "unsupported"
    support_level: str = "unsupported"
    confidence: float = 0.0
    severity: str = "medium"

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
            "support_type": self.support_type,
            "support_level": self.support_level,
            "confidence": self.confidence,
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
    rejected_claim_usage: list[RejectedClaimUsage] = field(default_factory=list)
    accepted_claim_ids: list[str] = field(default_factory=list)
    rejected_claim_ids: list[str] = field(default_factory=list)
    uncertain_claim_ids: list[str] = field(default_factory=list)
    high_severity_unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)

    @property
    def unsupported_sections(self) -> list[SectionSupport]:
        return [section for section in self.sections if not section.supported]

    @property
    def supported_claim_count(self) -> int:
        return sum(1 for section in self.sections for support in section.claim_supports if support.supported)

    @property
    def unsupported_claim_count(self) -> int:
        return len(self.unsupported_claims)

    @property
    def rejected_claim_usage_count(self) -> int:
        return len(self.rejected_claim_usage)

    @property
    def coverage_ratio(self) -> float:
        if not self.sections:
            return 0.0
        return round(
            sum(section.coverage_score for section in self.sections) / len(self.sections),
            4,
        )

    @property
    def section_claim_evidence_map(self) -> dict[str, dict[str, list[str]]]:
        return {
            section.section_id: {
                support.claim_id: list(support.evidence_ids)
                for support in section.claim_supports
            }
            for section in self.sections
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [section.to_dict() for section in self.sections],
            "section_claim_evidence_map": self.section_claim_evidence_map,
            "coverage_ratio": self.coverage_ratio,
            "supported_claim_count": self.supported_claim_count,
            "unsupported_claim_count": self.unsupported_claim_count,
            "rejected_claim_usage_count": self.rejected_claim_usage_count,
            "unsupported_sections": [
                section.section_title for section in self.unsupported_sections
            ],
            "unsupported_claims": [
                claim.to_dict() for claim in self.unsupported_claims
            ],
            "rejected_claim_usage": [
                usage.to_dict() for usage in self.rejected_claim_usage
            ],
            "accepted_claim_ids": list(self.accepted_claim_ids),
            "rejected_claim_ids": list(self.rejected_claim_ids),
            "uncertain_claim_ids": list(self.uncertain_claim_ids),
            "high_severity_unsupported_claims": [
                claim.to_dict() for claim in self.high_severity_unsupported_claims
            ],
        }


class SupportMatrixBuilder:
    def build(
        self,
        report: dict,
        evidence_bundle: EvidenceBundle,
        verified_findings: VerifiedFindings | None = None,
    ) -> SupportMatrix:
        evidence_by_url = {
            url: item
            for item in evidence_bundle.items
            for url in (item.source_urls or ([item.source_url] if item.source_url else []))
            if url
        }
        evidence_by_id = {item.evidence_id: item for item in evidence_bundle.items}
        accepted_by_claim_id = {
            claim.claim_id: claim for claim in (verified_findings.accepted_claims if verified_findings else [])
        }
        rejected_claims = verified_findings.rejected_claims if verified_findings else []
        uncertain_claims = verified_findings.uncertain_claims if verified_findings else []
        accepted_claim_ids = set(accepted_by_claim_id)
        rejected_claim_ids = {verified_claim.claim_id for verified_claim in rejected_claims}
        uncertain_claim_ids = {verified_claim.claim_id for verified_claim in uncertain_claims}
        report_claims = ClaimExtractor().extract(report_draft=report)
        claims_by_section: dict[str, list[Claim]] = {}
        for claim in report_claims:
            claims_by_section.setdefault(claim.section_id, []).append(claim)
        grounded_claims_by_section = _section_grounded_claims(report)

        sections: list[SectionSupport] = []
        unsupported_claims: list[UnsupportedClaim] = []
        rejected_usage: list[RejectedClaimUsage] = []

        for index, section in enumerate(report.get("sections", [])):
            section_id = _section_id(section, index)
            section_title = str(section.get("title", "Untitled"))
            cited_urls = _section_sources(section)
            cited_evidence_ids = _section_evidence_ids(section)
            candidate_items = _stable_items(
                [
                    *(evidence_by_url[url] for url in cited_urls if url in evidence_by_url),
                    *(evidence_by_id[evidence_id] for evidence_id in cited_evidence_ids if evidence_id in evidence_by_id),
                ]
            )
            claim_supports: list[ClaimSupport] = []
            section_claims = (
                []
                if _is_operational_source_note(section_title, str(section.get("content", "")))
                else claims_by_section.get(section_id, [])
            )
            for claim in section_claims:
                matched_items = _matched_items_for_claim(
                    claim,
                    section=section,
                    candidate_items=candidate_items,
                    evidence_by_id=evidence_by_id,
                    accepted_by_claim_id=accepted_by_claim_id,
                    grounded_claims=grounded_claims_by_section.get(section_id, {}),
                )
                support_level = _claim_support_level(
                    claim.claim_id,
                    accepted_claim_ids=accepted_claim_ids,
                    rejected_claim_ids=rejected_claim_ids,
                    uncertain_claim_ids=uncertain_claim_ids,
                    matched_items=matched_items,
                )
                support_type = "supports" if support_level in {"accepted", "supported"} else support_level
                support = ClaimSupport(
                    claim_id=claim.claim_id,
                    text=claim.text,
                    section_id=section_id,
                    evidence_ids=[item.evidence_id for item in matched_items],
                    cited_urls=cited_urls,
                    support_type=support_type,
                    support_level=support_level,
                    confidence=round(
                        max([item.confidence for item in matched_items], default=0.0),
                        4,
                    ),
                    severity=claim.severity,
                )
                claim_supports.append(support)
                if support_level == "unsupported":
                    unsupported_claims.append(
                        UnsupportedClaim(
                            claim_id=claim.claim_id,
                            text=claim.text,
                            section_id=section_id,
                            section_title=section_title,
                            severity=claim.severity,
                        )
                    )
            for rejected in rejected_claims:
                if section_claims and _claim_present_in_section(rejected.claim, section):
                    rejected_usage.append(
                        RejectedClaimUsage(
                            claim_id=rejected.claim_id,
                            text=rejected.claim,
                            section_id=section_id,
                            reason=rejected.rejection_reason or rejected.notes,
                        )
                    )
            matched_evidence_ids = _stable_strs(
                [
                    *(item.evidence_id for item in candidate_items),
                    *(
                        evidence_id
                        for support in claim_supports
                        for evidence_id in support.evidence_ids
                    ),
                ]
            )
            if claim_supports:
                coverage_score = round(
                    sum(1 for support in claim_supports if support.supported) / len(claim_supports),
                    4,
                )
            else:
                coverage_score = 1.0 if matched_evidence_ids else 0.0
            sections.append(
                SectionSupport(
                    section_id=section_id,
                    section_title=section_title,
                    cited_urls=cited_urls,
                    cited_evidence_ids=cited_evidence_ids,
                    matched_evidence_ids=matched_evidence_ids,
                    claim_supports=claim_supports,
                    matched_evidence_confidences=[
                        item.confidence for item in candidate_items
                    ],
                    coverage_score=coverage_score,
                    supported=bool(matched_evidence_ids) and coverage_score >= 1.0,
                )
            )
        return SupportMatrix(
            sections=sections,
            unsupported_claims=unsupported_claims,
            rejected_claim_usage=rejected_usage,
            accepted_claim_ids=sorted(accepted_by_claim_id),
            rejected_claim_ids=sorted({claim.claim_id for claim in rejected_claims}),
            uncertain_claim_ids=sorted({claim.claim_id for claim in uncertain_claims}),
            high_severity_unsupported_claims=[
                claim for claim in unsupported_claims if claim.severity == "high"
            ],
        )


def _matched_items_for_claim(
    claim: Claim,
    *,
    section: dict[str, Any],
    candidate_items: list[EvidenceItem],
    evidence_by_id: dict[str, EvidenceItem],
    accepted_by_claim_id: dict[str, Any],
    grounded_claims: dict[str, dict[str, Any]],
) -> list[EvidenceItem]:
    if claim.claim_id in accepted_by_claim_id:
        accepted = accepted_by_claim_id[claim.claim_id]
        return [
            evidence_by_id[evidence_id]
            for evidence_id in accepted.supporting_evidence_ids
            if evidence_id in evidence_by_id
        ]
    grounded_claim = grounded_claims.get(claim.claim_id) or _grounded_claim_for_text(
        claim.text,
        grounded_claims,
    )
    if grounded_claim:
        grounded_items = [
            evidence_by_id[evidence_id]
            for evidence_id in grounded_claim.get("evidence_ids", [])
            if evidence_id in evidence_by_id
        ]
        if grounded_items:
            return grounded_items
    explicit = [
        evidence_by_id[evidence_id]
        for evidence_id in claim.source_evidence_ids
        if evidence_id in evidence_by_id
    ]
    if explicit:
        return explicit
    section_explicit = [
        evidence_by_id[evidence_id]
        for evidence_id in _section_evidence_ids(section)
        if evidence_id in evidence_by_id
    ]
    if section_explicit:
        return section_explicit
    return [
        item
        for item in candidate_items
        if _claim_supported_by_evidence(claim.text, item)
    ]


def _claim_support_level(
    claim_id: str,
    *,
    accepted_claim_ids: set[str],
    rejected_claim_ids: set[str],
    uncertain_claim_ids: set[str],
    matched_items: list[EvidenceItem],
) -> str:
    if claim_id in accepted_claim_ids:
        return "accepted"
    if claim_id in rejected_claim_ids:
        return "rejected"
    if claim_id in uncertain_claim_ids:
        return "uncertain"
    if matched_items:
        return "supported"
    return "unsupported"
def _section_sources(section: dict) -> list[str]:
    sources = section.get("sources") or section.get("source_urls") or []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [source for source in sources if isinstance(source, str)]
    return []


def _section_evidence_ids(section: dict) -> list[str]:
    evidence_ids = section.get("evidence_ids") or section.get("citations") or []
    if isinstance(evidence_ids, str):
        return [evidence_ids]
    if isinstance(evidence_ids, list):
        return [
            value
            for value in (str(item) for item in evidence_ids if item is not None)
            if value
        ]
    return []


def _section_grounded_claims(report: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    grounded_by_section: dict[str, dict[str, dict[str, Any]]] = {}
    for index, section in enumerate(report.get("sections", [])):
        section_id = _section_id(section, index)
        claim_grounding = section.get("claim_grounding") or []
        if not isinstance(claim_grounding, list):
            continue
        grounded_claims: dict[str, dict[str, Any]] = {}
        for grounded_claim in claim_grounding:
            if not isinstance(grounded_claim, dict):
                continue
            claim_id = str(grounded_claim.get("claim_id") or "").strip()
            if not claim_id:
                continue
            grounded_claims[claim_id] = {
                "claim_id": claim_id,
                "text": str(grounded_claim.get("text") or grounded_claim.get("claim") or ""),
                "evidence_ids": _string_list(grounded_claim.get("evidence_ids") or []),
                "source_urls": _string_list(grounded_claim.get("source_urls") or grounded_claim.get("sources") or []),
            }
        if grounded_claims:
            grounded_by_section[section_id] = grounded_claims
    return grounded_by_section


def _grounded_claim_for_text(
    text: str,
    grounded_claims: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for grounded_claim in grounded_claims.values():
        grounded_text = str(grounded_claim.get("text") or "")
        if _claim_text_matches(text, grounded_text):
            return grounded_claim
    return None



def _section_id(section: dict[str, Any], section_index: int) -> str:
    section_id = section.get("section_id") or section.get("id")
    if section_id:
        return str(section_id)
    slug = re.sub(r"[^a-z0-9]+", "_", str(section.get("title", "")).casefold()).strip("_")
    return slug or f"section_{section_index + 1}"


def _claim_present_in_section(claim: str, section: dict[str, Any]) -> bool:
    section_text = _normalize(_section_text(section))
    normalized_claim = _normalize(claim)
    return bool(normalized_claim) and (
        normalized_claim in section_text
        or _token_overlap(claim, section_text) >= 0.75
    )


def _section_text(section: dict[str, Any]) -> str:
    parts = [str(section.get("title", "")), str(section.get("content", ""))]
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


def _claim_supported_by_evidence(claim: str, item: EvidenceItem) -> bool:
    evidence_text = f"{item.title} {item.summary}"
    atomic_claims = _atomic_claims(claim)
    if len(atomic_claims) > 1:
        return all(_single_claim_supported_by_evidence(part, evidence_text) for part in atomic_claims)
    return _single_claim_supported_by_evidence(claim, evidence_text)


def _claim_text_matches(left: str, right: str) -> bool:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if not normalized_left or not normalized_right:
        return False
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
        or _token_overlap(left, right) >= CLAIM_SUPPORT_TOKEN_OVERLAP_THRESHOLD
    )


def _is_low_information_claim(claim: str) -> bool:
    tokens = _tokens(claim)
    return 0 < len(tokens) <= 2


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


def _stable_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    result: list[EvidenceItem] = []
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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    return []


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
