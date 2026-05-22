from __future__ import annotations

from hashlib import sha256
from typing import Any

from business.foundation.models.source import RankedSourceItem
from business.layers.relation.evidence.claim_verifier import ClaimExtractor, ClaimVerifier
from business.layers.relation.evidence.models import EvidenceBuildResult, EvidenceBundle, EvidenceItem, EvidenceScore


class EvidenceBuilder:
    def build(
        self,
        ranked_items: list[RankedSourceItem],
        *,
        bundle_id: str = "daily",
        topic: str = "",
    ) -> EvidenceBundle:
        return self.build_with_scores(
            ranked_items,
            bundle_id=bundle_id,
            topic=topic,
        ).bundle

    def build_with_scores(
        self,
        ranked_items: list[RankedSourceItem],
        *,
        bundle_id: str = "daily",
        topic: str = "",
    ) -> EvidenceBuildResult:
        evidence_by_key: dict[str, EvidenceItem] = {}
        score_by_evidence_id: dict[str, EvidenceScore] = {}
        source_map: dict[str, list[str]] = {}
        for ranked in ranked_items:
            item = ranked.item
            evidence_key = _evidence_key(ranked)
            evidence_hash = sha256(evidence_key.encode("utf-8")).hexdigest()[:16]
            evidence_id = f"ev_{evidence_hash}"
            source_lineage = ranked.lineage or item.lineage
            raw_lineage = ranked.metadata.get("lineage") or item.metadata.get("lineage") or {}
            source_lineage_payload = (
                source_lineage.to_dict()
                if source_lineage is not None and hasattr(source_lineage, "to_dict")
                else (dict(raw_lineage) if isinstance(raw_lineage, dict) else {})
            )
            validation_notes = _evidence_validation_notes(ranked, source_lineage)
            content_completeness = _content_completeness_score(item.title, item.summary)
            extraction_signal = _source_extraction_confidence(ranked)
            evidence_score = _evidence_score(
                ranked,
                evidence_id=evidence_id,
                content_completeness_score=content_completeness,
                extraction_signal=extraction_signal,
                validation_notes=validation_notes,
            )
            evidence_item = EvidenceItem(
                evidence_id=evidence_id,
                source_url=item.canonical_url,
                title=item.title,
                summary=item.summary or item.title,
                confidence=evidence_score.final_confidence,
                source_id=item.source_id,
                source_item_id=item.source_item_id,
                source_item_ids=[item.source_item_id],
                source_urls=[item.canonical_url] if item.canonical_url else [],
                source_reliability=_source_reliability(item.source_reliability),
                publishable=bool(item.canonical_url) and not validation_notes,
                lineage=source_lineage,
                metadata={
                    "ranked_item_id": ranked.ranked_item_id,
                    "final_score": ranked.final_score,
                    "rank_reason": ranked.rank_reason,
                    "source_lineage": source_lineage_payload,
                    "content_completeness_score": content_completeness,
                    "source_extraction_confidence_score": extraction_signal["score"],
                    "source_extraction_confidence_basis": extraction_signal["basis"],
                    "validation_notes": validation_notes,
                    "confidence_basis": (
                        "source_reliability+recency+content_completeness; "
                        "LLM subjective confidence is not used"
                    ),
                },
            )
            if evidence_key in evidence_by_key:
                evidence_by_key[evidence_key] = _merge_evidence_items(
                    evidence_by_key[evidence_key],
                    evidence_item,
                )
                score_by_evidence_id[evidence_id] = _merge_evidence_scores(
                    score_by_evidence_id[evidence_id],
                    evidence_score,
                )
            else:
                evidence_by_key[evidence_key] = evidence_item
                score_by_evidence_id[evidence_id] = evidence_score
            if item.canonical_url:
                source_map.setdefault(item.canonical_url, [])
                if evidence_id not in source_map[item.canonical_url]:
                    source_map[item.canonical_url].append(evidence_id)
        evidence_items = list(evidence_by_key.values())
        evidence_scores = list(score_by_evidence_id.values())
        bundle = EvidenceBundle(
            bundle_id=bundle_id,
            topic=topic,
            items=evidence_items,
            source_map=source_map,
            missing_information=[] if evidence_items else ["no ranked source items were available"],
            coverage_notes=[
                f"Built {len(evidence_items)} evidence item(s) from {len(source_map)} source URL(s)."
            ],
            source_coverage={
                "item_count": len(evidence_items),
                "input_item_count": len(ranked_items),
                "source_url_count": len(source_map),
                "source_count": len({item.source_id for item in evidence_items if item.source_id}),
                "publishable_item_count": sum(1 for item in evidence_items if item.publishable),
                "merged_duplicate_count": max(0, len(ranked_items) - len(evidence_items)),
            },
            metadata={"evidence_count": len(evidence_items), "source_url_count": len(source_map)},
        )
        candidate_claims = ClaimExtractor().extract(bundle)
        verified_findings = ClaimVerifier().verify(list(candidate_claims), bundle)
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
    content_completeness_score: float,
    extraction_signal: dict[str, float | str],
    validation_notes: list[str],
) -> EvidenceScore:
    final_confidence = round(
        min(
            1.0,
            max(
                0.05,
                ranked.reliability_score * 0.45
                + ranked.recency_score * 0.35
                + content_completeness_score * 0.20,
            ),
        ),
        4,
    )
    if validation_notes:
        final_confidence = round(min(final_confidence, 0.35), 4)
    specificity_score = _specificity_score(ranked.item.title, ranked.item.summary)
    return EvidenceScore(
        evidence_id=evidence_id,
        source_reliability_score=round(ranked.reliability_score, 4),
        freshness_score=round(ranked.recency_score, 4),
        specificity_score=specificity_score,
        corroboration_score=0.5,
        extraction_confidence_score=float(extraction_signal["score"]),
        final_confidence=final_confidence,
        score_reason=(
            "final confidence is deterministic from source reliability, recency, and "
            "content completeness; LLM subjective confidence is not used"
            f"; extraction_basis={extraction_signal['basis']}"
            + (f"; validation_notes={','.join(validation_notes)}" if validation_notes else "")
        ),
    )


def _specificity_score(title: str, summary: str | None) -> float:
    text = " ".join(part for part in [title, summary or ""] if part).strip()
    if len(text) >= 120:
        return 1.0
    if len(text) >= 60:
        return 0.8
    return 0.6


def _content_completeness_score(title: str, summary: str | None) -> float:
    title_score = 0.35 if title.strip() else 0.0
    summary_text = (summary or "").strip()
    if len(summary_text) >= 120:
        summary_score = 0.65
    elif len(summary_text) >= 40:
        summary_score = 0.45
    elif summary_text:
        summary_score = 0.4
    else:
        summary_score = 0.0
    return round(min(1.0, title_score + summary_score), 4)


def _source_extraction_confidence(ranked: RankedSourceItem) -> dict[str, float | str]:
    metadata = ranked.item.metadata
    for key in ("extraction_confidence", "source_extraction_confidence"):
        if key in metadata:
            return {"score": _clamp_score(metadata[key]), "basis": key}
    nested = metadata.get("extraction")
    if isinstance(nested, dict) and "confidence" in nested:
        return {"score": _clamp_score(nested["confidence"]), "basis": "extraction.confidence"}
    return {"score": 0.5, "basis": "default_unknown"}


def _clamp_score(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.5
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return round(min(1.0, max(0.0, number)), 4)


def _evidence_key(ranked: RankedSourceItem) -> str:
    item = ranked.item
    if item.canonical_url:
        return f"url:{item.canonical_url}"
    text = " ".join(part for part in [item.title, item.summary or ""] if part)
    return f"text:{sha256(text.casefold().encode('utf-8')).hexdigest()}"


def _evidence_validation_notes(ranked: RankedSourceItem, lineage: Any) -> list[str]:
    notes: list[str] = []
    if not ranked.item.source_item_id:
        notes.append("missing_source_item_id")
    if not ranked.item.canonical_url:
        notes.append("missing_source_url")
    if lineage is None:
        notes.append("missing_lineage")
    elif not getattr(lineage, "source_item_id", None):
        notes.append("missing_lineage_source_item_id")
    return notes


def _merge_evidence_items(existing: EvidenceItem, incoming: EvidenceItem) -> EvidenceItem:
    source_item_ids = _stable_unique([*existing.source_item_ids, *incoming.source_item_ids])
    source_urls = _stable_unique([*existing.source_urls, *incoming.source_urls])
    metadata = dict(existing.metadata)
    metadata["merged_source_item_ids"] = source_item_ids
    metadata["merged_ranked_item_ids"] = _stable_unique(
        [
            *metadata.get("merged_ranked_item_ids", []),
            metadata.get("ranked_item_id"),
            incoming.metadata.get("ranked_item_id"),
        ]
    )
    metadata["validation_notes"] = _stable_unique(
        [
            *metadata.get("validation_notes", []),
            *incoming.metadata.get("validation_notes", []),
        ]
    )
    return EvidenceItem(
        evidence_id=existing.evidence_id,
        source_url=existing.source_url or incoming.source_url,
        title=existing.title,
        summary=_longer(existing.summary, incoming.summary),
        confidence=round(max(existing.confidence, incoming.confidence), 4),
        source_id=existing.source_id,
        source_item_id=source_item_ids[0] if source_item_ids else existing.source_item_id,
        source_item_ids=source_item_ids,
        source_urls=source_urls,
        source_reliability=existing.source_reliability or incoming.source_reliability,
        publishable=existing.publishable and incoming.publishable,
        evidence_type=existing.evidence_type,
        lineage=existing.lineage or incoming.lineage,
        metadata=metadata,
    )


def _merge_evidence_scores(existing: EvidenceScore, incoming: EvidenceScore) -> EvidenceScore:
    return EvidenceScore(
        evidence_id=existing.evidence_id,
        source_reliability_score=round(
            max(existing.source_reliability_score, incoming.source_reliability_score),
            4,
        ),
        freshness_score=round(max(existing.freshness_score, incoming.freshness_score), 4),
        specificity_score=round(max(existing.specificity_score, incoming.specificity_score), 4),
        corroboration_score=round(min(1.0, max(existing.corroboration_score, incoming.corroboration_score) + 0.1), 4),
        extraction_confidence_score=round(
            max(existing.extraction_confidence_score, incoming.extraction_confidence_score),
            4,
        ),
        final_confidence=round(max(existing.final_confidence, incoming.final_confidence), 4),
        score_reason=f"{existing.score_reason}; duplicate evidence merged with all source ids retained",
    )


def _stable_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _longer(left: str, right: str) -> str:
    return left if len(left) >= len(right) else right


def _source_reliability(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)
