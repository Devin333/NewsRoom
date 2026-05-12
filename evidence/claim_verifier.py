from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from domain.sources import Lineage
from evidence.models import Claim, EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings


class ClaimExtractor:
    def extract(self, evidence_bundle: EvidenceBundle) -> list[Claim]:
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
                    source_evidence_ids=[item.evidence_id],
                    source_urls=[item.source_url],
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
                rejected.append(
                    VerifiedClaim(
                        claim_id=claim.claim_id,
                        claim=claim.text,
                        status="rejected",
                        confidence=1.0,
                        rejecting_evidence_ids=outside_ids,
                        rejecting_sources=outside_urls,
                        notes="claim references evidence outside the bundle",
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
                        verification_method="rule",
                        lineage=claim.lineage or matched_items[0].lineage,
                    )
                )
                continue

            uncertain.append(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    claim=claim.text,
                    status="uncertain",
                    confidence=round(claim.confidence if claim.confidence is not None else 0.4, 4),
                    notes="claim has no direct evidence mapping",
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


def _coerce_claim(raw_claim: Claim | dict[str, Any] | str) -> Claim:
    if isinstance(raw_claim, Claim):
        return raw_claim
    if isinstance(raw_claim, str):
        text = raw_claim.strip()
        return Claim(
            claim_id=f"claim_{sha256(_normalize(text).encode('utf-8')).hexdigest()[:16]}",
            text=text,
            claim_type=_claim_type(text),
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
        if _token_overlap(text, f"{item.title} {item.summary}") >= 0.45:
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
