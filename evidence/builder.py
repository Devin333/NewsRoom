from __future__ import annotations

from hashlib import sha256

from domain.sources import RankedSourceItem
from evidence.claim_verifier import ClaimExtractor, ClaimVerifier
from evidence.models import EvidenceBuildResult, EvidenceBundle, EvidenceItem, EvidenceScore


class EvidenceBuilder:
    def build(self, ranked_items: list[RankedSourceItem], *, bundle_id: str = "daily") -> EvidenceBundle:
        return self.build_with_scores(ranked_items, bundle_id=bundle_id).bundle

    def build_with_scores(
        self,
        ranked_items: list[RankedSourceItem],
        *,
        bundle_id: str = "daily",
    ) -> EvidenceBuildResult:
        evidence_items = []
        evidence_scores = []
        source_map: dict[str, list[str]] = {}
        for ranked in ranked_items:
            item = ranked.item
            evidence_hash = sha256(item.canonical_url.encode("utf-8")).hexdigest()[:16]
            evidence_id = f"ev_{evidence_hash}"
            source_lineage = ranked.lineage or item.lineage
            source_lineage_payload = (
                source_lineage.to_dict()
                if hasattr(source_lineage, "to_dict")
                else dict(ranked.metadata.get("lineage") or item.metadata.get("lineage") or {})
            )
            extraction_signal = _source_extraction_confidence(ranked)
            evidence_score = _evidence_score(
                ranked,
                evidence_id=evidence_id,
                extraction_signal=extraction_signal,
            )
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    source_url=item.canonical_url,
                    title=item.title,
                    summary=item.summary or item.title,
                    confidence=evidence_score.final_confidence,
                    source_id=item.source_id,
                    lineage=source_lineage,
                    metadata={
                        "ranked_item_id": ranked.ranked_item_id,
                        "final_score": ranked.final_score,
                        "rank_reason": ranked.rank_reason,
                        "source_lineage": source_lineage_payload,
                        "source_extraction_confidence_score": extraction_signal["score"],
                        "source_extraction_confidence_basis": extraction_signal["basis"],
                    },
                )
            )
            evidence_scores.append(evidence_score)
            source_map.setdefault(item.canonical_url, []).append(evidence_id)
        bundle = EvidenceBundle(
            bundle_id=bundle_id,
            items=evidence_items,
            source_map=source_map,
            missing_information=[] if evidence_items else ["no ranked source items were available"],
            coverage_notes=[
                f"Built {len(evidence_items)} evidence item(s) from {len(source_map)} source URL(s)."
            ],
            metadata={"evidence_count": len(evidence_items), "source_url_count": len(source_map)},
        )
        candidate_claims = ClaimExtractor().extract(bundle)
        verified_findings = ClaimVerifier().verify(candidate_claims, bundle)
        return EvidenceBuildResult(
            bundle=bundle,
            evidence_scores=evidence_scores,
            candidate_claims=candidate_claims,
            verified_findings=verified_findings,
        )


def _evidence_score(
    ranked: RankedSourceItem,
    *,
    evidence_id: str,
    extraction_signal: dict[str, float | str],
) -> EvidenceScore:
    item = ranked.item
    final_confidence = round(min(1.0, max(0.1, ranked.final_score)), 4)
    specificity_score = _specificity_score(item.title, item.summary)
    return EvidenceScore(
        evidence_id=evidence_id,
        source_reliability_score=round(ranked.reliability_score, 4),
        freshness_score=round(ranked.recency_score, 4),
        specificity_score=specificity_score,
        corroboration_score=0.5,
        extraction_confidence_score=float(extraction_signal["score"]),
        final_confidence=final_confidence,
        score_reason=(
            "final confidence follows ranked source score; component scores preserve "
            "reliability, freshness, specificity, corroboration, and source-derived "
            f"extraction signals; extraction_basis={extraction_signal['basis']}"
        ),
    )


def _source_extraction_confidence(ranked: RankedSourceItem) -> dict[str, float | str]:
    metadata = ranked.item.metadata
    for key in ("extraction_confidence", "source_extraction_confidence"):
        if key in metadata:
            return {"score": _clamp_score(metadata[key]), "basis": key}
    nested = metadata.get("extraction")
    if isinstance(nested, dict) and "confidence" in nested:
        return {"score": _clamp_score(nested["confidence"]), "basis": "extraction.confidence"}
    return {"score": 0.5, "basis": "default_unknown"}


def _specificity_score(title: str, summary: str | None) -> float:
    text = " ".join(part for part in [title, summary or ""] if part).strip()
    if len(text) >= 120:
        return 1.0
    if len(text) >= 60:
        return 0.8
    return 0.6


def _clamp_score(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return round(min(1.0, max(0.0, number)), 4)
