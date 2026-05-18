from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from domain.sources import Lineage
from evidence.models import Claim, EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings


class ClaimExtractor:
    def extract(
        self,
        evidence_bundle: EvidenceBundle | None = None,
        *,
        report_draft: dict[str, Any] | None = None,
        findings: dict[str, Any] | VerifiedFindings | None = None,
    ) -> list[Claim]:
        if report_draft is not None:
            return self.extract_from_report(report_draft)
        if findings is not None:
            return self.extract_from_findings(findings)
        if evidence_bundle is None:
            return []
        return self.extract_from_evidence(evidence_bundle)

    def extract_from_evidence(self, evidence_bundle: EvidenceBundle) -> list[Claim]:
        claims: list[Claim] = []
        seen: set[str] = set()
        for item in evidence_bundle.items:
            text = _claim_text_from_evidence(item)
            normalized = _normalize(text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            claim_type = _claim_type(text)
            confidence = item.confidence
            if claim_type in {"prediction", "trend"}:
                confidence = min(confidence, 0.7)
            claims.append(
                Claim(
                    claim_id=f"claim_{sha256(normalized.encode('utf-8')).hexdigest()[:16]}",
                    text=text,
                    claim_type=claim_type,
                    section_id="evidence",
                    severity=_claim_severity(text),
                    importance=_claim_importance(text),
                    source_evidence_ids=[item.evidence_id],
                    source_urls=list(item.source_urls or ([item.source_url] if item.source_url else [])),
                    confidence=round(confidence, 4),
                    created_by_agent_id="evidence.claim_extractor.rule",
                    lineage=item.lineage,
                    metadata={
                        "extraction_method": "evidence_title_summary_rule",
                        "source_id": item.source_id,
                    },
                )
            )
        return claims

    def extract_from_report(self, report_draft: dict[str, Any]) -> list[Claim]:
        claims: list[Claim] = []
        seen: set[str] = set()
        for section_index, section in enumerate(report_draft.get("sections", [])):
            section_id = str(
                section.get("section_id")
                or section.get("id")
                or _section_id(section.get("title"), section_index)
            )
            sources = _list_str(section.get("sources") or section.get("source_urls") or [])
            evidence_ids = _section_evidence_ids(section)
            explicit_claims = _claims_from_section_grounding(
                section,
                section_id=section_id,
                sources=sources,
                evidence_ids=evidence_ids,
            )
            grounded_texts = [claim.text for claim in explicit_claims]
            for claim in explicit_claims:
                normalized = _normalize(claim.text)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                claims.append(claim)
            for text in _section_claims(section):
                normalized = _normalize(text)
                if not normalized or normalized in seen:
                    continue
                if any(_claim_matches_text(text, grounded_text) for grounded_text in grounded_texts):
                    continue
                seen.add(normalized)
                claims.append(
                    Claim(
                        claim_id=f"claim_{sha256(f'{section_id}:{normalized}'.encode('utf-8')).hexdigest()[:16]}",
                        text=text,
                        claim_type=_claim_type(text),
                        section_id=section_id,
                        severity=_claim_severity(text),
                        importance=_claim_importance(text),
                        source_evidence_ids=evidence_ids,
                        source_urls=sources,
                        created_by_agent_id="evidence.claim_extractor.report_rule",
                        metadata={"extraction_method": "report_section_rule"},
                    )
                )
        return claims

    def extract_from_findings(
        self,
        findings: dict[str, Any] | VerifiedFindings,
    ) -> list[Claim]:
        if isinstance(findings, VerifiedFindings):
            raw_claims: list[Any] = findings.all_claims
        else:
            raw_claims = []
            for key in ("claims", "accepted_claims", "rejected_claims", "uncertain_claims"):
                value = findings.get(key, [])
                if isinstance(value, list):
                    raw_claims.extend(value)
        return [_claim_from_verified_or_raw(raw_claim) for raw_claim in raw_claims]


class ClaimVerifier:
    def verify(
        self,
        candidate_claims: list[Claim | dict[str, Any] | str],
        evidence_bundle: EvidenceBundle,
    ) -> VerifiedFindings:
        evidence_by_id = {item.evidence_id: item for item in evidence_bundle.items}
        evidence_by_url = {item.source_url: item for item in evidence_bundle.items}
        accepted: list[VerifiedClaim] = []
        rejected: list[VerifiedClaim] = []
        uncertain: list[VerifiedClaim] = []

        for raw_claim in candidate_claims:
            claim = _coerce_claim(raw_claim)
            source_urls = sorted(set(claim.source_urls))
            source_evidence_ids = sorted(set(claim.source_evidence_ids))
            outside_urls = [url for url in source_urls if url not in evidence_by_url]
            outside_ids = [evidence_id for evidence_id in source_evidence_ids if evidence_id not in evidence_by_id]

            if outside_urls or outside_ids:
                reason = "claim references evidence outside the bundle"
                rejected.append(
                    VerifiedClaim(
                        claim_id=claim.claim_id,
                        claim=claim.text,
                        status="rejected",
                        confidence=1.0,
                        rejecting_evidence_ids=outside_ids,
                        rejecting_sources=outside_urls,
                        notes=reason,
                        rejection_reason=reason,
                        section_id=claim.section_id,
                        severity=claim.severity,
                        importance=claim.importance,
                        verification_method="rule",
                        lineage=claim.lineage,
                    )
                )
                continue

            matched_items = [
                evidence_by_id[evidence_id]
                for evidence_id in source_evidence_ids
                if evidence_id in evidence_by_id
            ]
            matched_items.extend(
                item for url, item in evidence_by_url.items() if url in source_urls and item not in matched_items
            )
            if not matched_items:
                matched_items = _text_supported_items(claim.text, evidence_bundle.items)

            if matched_items:
                confidence = max(item.confidence for item in matched_items)
                if claim.confidence is not None:
                    confidence = min(confidence, claim.confidence)
                accepted.append(
                    VerifiedClaim(
                        claim_id=claim.claim_id,
                        claim=claim.text,
                        status="accepted",
                        confidence=round(confidence, 4),
                        supporting_evidence_ids=[item.evidence_id for item in matched_items],
                        supporting_sources=[item.source_url for item in matched_items],
                        notes="claim is supported by evidence in the bundle",
                        section_id=claim.section_id,
                        severity=claim.severity,
                        importance=claim.importance,
                        verification_method="rule",
                        lineage=claim.lineage or matched_items[0].lineage,
                    )
                )
                continue

            reason = "claim has no direct evidence mapping"
            uncertain.append(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    claim=claim.text,
                    status="uncertain",
                    confidence=round(claim.confidence if claim.confidence is not None else 0.4, 4),
                    notes=reason,
                    uncertainty_reason=reason,
                    section_id=claim.section_id,
                    severity=claim.severity,
                    importance=claim.importance,
                    verification_method="rule",
                    lineage=claim.lineage,
                )
            )

        return VerifiedFindings(
            accepted_claims=accepted,
            rejected_claims=rejected,
            uncertain_claims=uncertain,
            verification_summary=(
                f"Verified {len(candidate_claims)} claim(s): "
                f"{len(accepted)} accepted, {len(rejected)} rejected, {len(uncertain)} uncertain."
            ),
            metadata={
                "verification_method": "rule",
                "evidence_bundle_id": evidence_bundle.bundle_id,
            },
        )


def _claim_text_from_evidence(item: EvidenceItem) -> str:
    title = item.title.strip()
    summary = item.summary.strip()
    if summary and _normalize(summary) != _normalize(title):
        return f"{title}: {summary}"
    return title


def _claim_type(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ["risk", "threat", "concern", "vulnerability"]):
        return "risk"
    if any(token in lowered for token in ["forecast", "expected", "will ", "likely", "may ", "could "]):
        return "prediction"
    if any(token in lowered for token in ["trend", "increase", "decrease", "growth", "decline"]):
        return "trend"
    if any(token in lowered for token in ["compared", "versus", "vs.", "more than", "less than"]):
        return "comparison"
    if any(token in lowered for token in ["recommend", "should", "must"]):
        return "recommendation"
    if any(token in lowered for token in ["historical", "previously", "last year", "in 20"]):
        return "historical_context"
    return "fact"


def _claim_severity(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ["critical", "breach", "vulnerability", "illegal", "safety"]):
        return "high"
    if any(token in lowered for token in ["risk", "may", "could", "expected", "likely"]):
        return "medium"
    return "low"


def _claim_importance(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ["critical", "major", "announced", "launched", "blocked"]):
        return "high"
    if len(_tokens(text)) >= 6:
        return "medium"
    return "low"


def _coerce_claim(raw_claim: Claim | dict[str, Any] | str) -> Claim:
    if isinstance(raw_claim, Claim):
        return raw_claim
    if isinstance(raw_claim, str):
        text = raw_claim.strip()
        return Claim(
            claim_id=f"claim_{sha256(_normalize(text).encode('utf-8')).hexdigest()[:16]}",
            text=text,
            claim_type=_claim_type(text),
            section_id="global",
            severity=_claim_severity(text),
            importance=_claim_importance(text),
        )
    text = str(raw_claim.get("text") or raw_claim.get("claim") or "").strip()
    claim_id = str(
        raw_claim.get("claim_id")
        or f"claim_{sha256(_normalize(text).encode('utf-8')).hexdigest()[:16]}"
    )
    return Claim(
        claim_id=claim_id,
        text=text,
        claim_type=str(raw_claim.get("claim_type") or _claim_type(text)),
        section_id=str(raw_claim.get("section_id") or "global"),
        severity=str(raw_claim.get("severity") or _claim_severity(text)),
        importance=str(raw_claim.get("importance") or _claim_importance(text)),
        source_evidence_ids=[str(value) for value in raw_claim.get("source_evidence_ids", [])],
        source_urls=[str(value) for value in raw_claim.get("source_urls", [])],
        confidence=(
            float(raw_claim["confidence"])
            if raw_claim.get("confidence") is not None
            else None
        ),
        created_by_agent_id=(
            str(raw_claim["created_by_agent_id"])
            if raw_claim.get("created_by_agent_id") is not None
            else None
        ),
        lineage=_coerce_lineage(raw_claim.get("lineage")),
        metadata=dict(raw_claim.get("metadata") or {}),
    )


def _claim_from_verified_or_raw(raw_claim: Any) -> Claim:
    if isinstance(raw_claim, Claim):
        return raw_claim
    if isinstance(raw_claim, VerifiedClaim):
        return Claim(
            claim_id=raw_claim.claim_id,
            text=raw_claim.claim,
            claim_type=_claim_type(raw_claim.claim),
            section_id=raw_claim.section_id,
            severity=raw_claim.severity,
            importance=raw_claim.importance,
            source_evidence_ids=list(raw_claim.supporting_evidence_ids),
            source_urls=list(raw_claim.supporting_sources),
            confidence=raw_claim.confidence,
            lineage=raw_claim.lineage,
            metadata={"source_status": raw_claim.status},
        )
    return _coerce_claim(raw_claim)


def _coerce_lineage(value: Any) -> Lineage | None:
    if value is None:
        return None
    if isinstance(value, Lineage):
        return value
    if isinstance(value, dict) and value.get("source_id"):
        return Lineage.from_dict(value)
    return None


def _text_supported_items(text: str, evidence_items: list[EvidenceItem]) -> list[EvidenceItem]:
    matches = []
    for item in evidence_items:
        evidence_text = f"{item.title} {item.summary}"
        if _normalize(text) in _normalize(evidence_text) or _token_overlap(text, evidence_text) >= 0.75:
            matches.append(item)
    return matches


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


def _section_id(title: Any, section_index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(title or "").casefold()).strip("_")
    return slug or f"section_{section_index + 1}"


def _section_claims(section: dict[str, Any]) -> list[str]:
    content = str(section.get("content", "")).strip()
    bullets = section.get("bullets") or []
    candidates: list[str] = []
    if content:
        candidates.extend(
            sentence.strip(" -")
            for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", content)
            if sentence.strip(" -")
        )
    if isinstance(bullets, list):
        candidates.extend(str(bullet).strip() for bullet in bullets if str(bullet).strip())
    return [claim for claim in candidates if len(_tokens(claim)) >= 2]


def _section_evidence_ids(section: dict[str, Any]) -> list[str]:
    values = []
    evidence_ids = section.get("evidence_ids") or []
    citations = section.get("citations") or []
    if isinstance(evidence_ids, list):
        values.extend(evidence_ids)
    elif isinstance(evidence_ids, str):
        values.append(evidence_ids)
    if isinstance(citations, list):
        values.extend(
            citation.get("evidence_id") if isinstance(citation, dict) else citation
            for citation in citations
        )
    elif isinstance(citations, str):
        values.append(citations)
    return [str(value) for value in values if value is not None and str(value)]


def _claims_from_section_grounding(
    section: dict[str, Any],
    *,
    section_id: str,
    sources: list[str],
    evidence_ids: list[str],
) -> list[Claim]:
    claim_grounding = section.get("claim_grounding") or []
    if not isinstance(claim_grounding, list):
        return []
    claims: list[Claim] = []
    for index, grounded_claim in enumerate(claim_grounding):
        if not isinstance(grounded_claim, dict):
            continue
        text = str(grounded_claim.get("text") or grounded_claim.get("claim") or "").strip()
        if not text:
            continue
        grounded_evidence_ids = _list_str(grounded_claim.get("evidence_ids") or []) or list(evidence_ids)
        grounded_sources = _list_str(grounded_claim.get("source_urls") or grounded_claim.get("sources") or []) or list(sources)
        claim_id = str(
            grounded_claim.get("claim_id")
            or f"claim_{sha256(f'{section_id}:{_normalize(text)}'.encode('utf-8')).hexdigest()[:16]}"
        )
        claims.append(
            Claim(
                claim_id=claim_id,
                text=text,
                claim_type=_claim_type(text),
                section_id=section_id,
                severity=str(grounded_claim.get("severity") or _claim_severity(text)),
                importance=str(grounded_claim.get("importance") or _claim_importance(text)),
                source_evidence_ids=grounded_evidence_ids,
                source_urls=grounded_sources,
                created_by_agent_id="evidence.claim_extractor.report_grounding_rule",
                metadata={
                    "extraction_method": "report_claim_grounding",
                    "claim_grounding_index": index,
                },
            )
        )
    return claims


def _claim_matches_text(left: str, right: str) -> bool:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if not normalized_left or not normalized_right:
        return False
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
        or _token_overlap(left, right) >= 0.75
    )


def _list_str(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return []


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
