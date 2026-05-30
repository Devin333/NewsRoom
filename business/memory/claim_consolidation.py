from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from difflib import SequenceMatcher
from typing import Literal

from business.memory.intelligence_builder import normalize_text_key
from business.memory.intelligence_models import ClaimMemory, utc_now


NEGATION_MARKERS = [
    "not",
    "no longer",
    "denied",
    "false",
    "rejected",
    "cancelled",
    "canceled",
    "withdrawn",
]


@dataclass(frozen=True)
class ClaimConsolidationAction:
    action_type: Literal["insert", "merge", "contradict", "outdate", "reject"]
    new_claim: ClaimMemory
    existing_claim: ClaimMemory | None = None
    result_claim: ClaimMemory | None = None
    reason: str | None = None
    confidence_delta: float = 0.0


@dataclass(frozen=True)
class ClaimConsolidationResult:
    actions: list[ClaimConsolidationAction]
    inserted: list[ClaimMemory] = field(default_factory=list)
    merged: list[ClaimMemory] = field(default_factory=list)
    contradicted: list[ClaimMemory] = field(default_factory=list)
    rejected: list[ClaimMemory] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "inserted": len(self.inserted),
            "merged": len(self.merged),
            "contradicted": len(self.contradicted),
            "rejected": len(self.rejected),
            "actions": len(self.actions),
        }


class ClaimConsolidator:
    def __init__(
        self,
        *,
        similarity_threshold: float = 0.92,
        contradiction_threshold: float = 0.75,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.contradiction_threshold = contradiction_threshold

    def consolidate(
        self,
        new_claims: list[ClaimMemory],
        existing_claims: list[ClaimMemory],
    ) -> ClaimConsolidationResult:
        actions: list[ClaimConsolidationAction] = []
        inserted: list[ClaimMemory] = []
        merged: list[ClaimMemory] = []
        contradicted: list[ClaimMemory] = []
        rejected: list[ClaimMemory] = []
        working_existing = list(existing_claims)

        for claim in new_claims:
            contradiction = self.find_contradicting_claim(claim, working_existing)
            if contradiction is not None:
                result_claim = self.mark_contradicted(claim, contradiction)
                contradicted.append(result_claim)
                actions.append(
                    ClaimConsolidationAction(
                        action_type="contradict",
                        new_claim=claim,
                        existing_claim=contradiction,
                        result_claim=result_claim,
                        reason="deterministic_negation_match",
                        confidence_delta=result_claim.confidence - claim.confidence,
                    )
                )
                working_existing.append(result_claim)
                continue

            match = self.find_matching_claim(claim, working_existing)
            if match is not None:
                result_claim = self.merge_claim(claim, match)
                merged.append(result_claim)
                actions.append(
                    ClaimConsolidationAction(
                        action_type="merge",
                        new_claim=claim,
                        existing_claim=match,
                        result_claim=result_claim,
                        reason="duplicate_claim",
                        confidence_delta=result_claim.confidence - match.confidence,
                    )
                )
                working_existing = [result_claim if item.claim_id == match.claim_id else item for item in working_existing]
                continue

            inserted.append(claim)
            actions.append(
                ClaimConsolidationAction(
                    action_type="insert",
                    new_claim=claim,
                    result_claim=claim,
                    reason="new_claim",
                )
            )
            working_existing.append(claim)

        return ClaimConsolidationResult(
            actions=actions,
            inserted=inserted,
            merged=merged,
            contradicted=contradicted,
            rejected=rejected,
        )

    def find_matching_claim(
        self,
        claim: ClaimMemory,
        existing_claims: list[ClaimMemory],
    ) -> ClaimMemory | None:
        for existing in existing_claims:
            if self.is_duplicate(claim, existing):
                return existing
        best: ClaimMemory | None = None
        best_score = 0.0
        for existing in existing_claims:
            score = _similarity(claim.normalized_text(), existing.normalized_text())
            if score > best_score:
                best = existing
                best_score = score
        return best if best is not None and best_score >= self.similarity_threshold else None

    def find_contradicting_claim(
        self,
        claim: ClaimMemory,
        existing_claims: list[ClaimMemory],
    ) -> ClaimMemory | None:
        for existing in existing_claims:
            if self.is_contradiction(claim, existing):
                return existing
        return None

    def is_duplicate(
        self,
        left: ClaimMemory,
        right: ClaimMemory,
    ) -> bool:
        if left.claim_id == right.claim_id:
            return True
        if left.normalized_text() == right.normalized_text():
            return True
        if (
            left.subject_entity_id
            and left.subject_entity_id == right.subject_entity_id
            and left.predicate
            and left.predicate == right.predicate
            and left.object_entity_id
            and left.object_entity_id == right.object_entity_id
        ):
            return True
        return False

    def is_contradiction(
        self,
        left: ClaimMemory,
        right: ClaimMemory,
    ) -> bool:
        same_subject = bool(left.subject_entity_id and left.subject_entity_id == right.subject_entity_id)
        same_predicate = bool(left.predicate and left.predicate == right.predicate)
        if same_subject and same_predicate:
            return _has_negation(left.text) != _has_negation(right.text)

        left_text = _strip_negation(left.normalized_text())
        right_text = _strip_negation(right.normalized_text())
        if left_text and right_text and _similarity(left_text, right_text) >= self.contradiction_threshold:
            return _has_negation(left.text) != _has_negation(right.text)
        return False

    def merge_claim(
        self,
        new_claim: ClaimMemory,
        existing_claim: ClaimMemory,
    ) -> ClaimMemory:
        evidence_ids = sorted({*existing_claim.evidence_ids, *new_claim.evidence_ids})
        contradicted_by = sorted({*existing_claim.contradicted_by, *new_claim.contradicted_by})
        metadata = {
            **existing_claim.metadata,
            **new_claim.metadata,
            "consolidation": "merged",
            "merged_claim_id": new_claim.claim_id,
        }
        source_count = _source_count(existing_claim, new_claim)
        confidence = self.recalculate_confidence(
            existing_claim,
            evidence_count=len(evidence_ids),
            source_count=source_count,
            contradiction_count=len(contradicted_by),
        )
        return replace(
            existing_claim,
            confidence=confidence,
            evidence_ids=evidence_ids,
            contradicted_by=contradicted_by,
            status="contradicted" if contradicted_by else existing_claim.status,
            first_seen_at=min_dt(existing_claim.first_seen_at, new_claim.first_seen_at),
            last_seen_at=max_dt(existing_claim.last_seen_at, new_claim.last_seen_at, utc_now()),
            metadata=metadata,
        )

    def mark_contradicted(self, new_claim: ClaimMemory, existing_claim: ClaimMemory) -> ClaimMemory:
        evidence_ids = sorted({*existing_claim.evidence_ids, *new_claim.evidence_ids})
        evidence_id = new_claim.evidence_ids[0] if new_claim.evidence_ids else new_claim.claim_id
        confidence = self.recalculate_confidence(
            existing_claim,
            evidence_count=len(evidence_ids),
            source_count=_source_count(existing_claim, new_claim),
            contradiction_count=max(1, len(existing_claim.contradicted_by) + 1),
        )
        contradicted = existing_claim.mark_contradicted(evidence_id, reason="deterministic_negation_match")
        return replace(
            contradicted,
            confidence=confidence,
            evidence_ids=evidence_ids,
            last_seen_at=max_dt(existing_claim.last_seen_at, new_claim.last_seen_at, utc_now()),
            metadata={
                **contradicted.metadata,
                "contradicting_claim_id": new_claim.claim_id,
                "contradicting_text": new_claim.text,
            },
        )

    def recalculate_confidence(
        self,
        claim: ClaimMemory,
        *,
        evidence_count: int,
        source_count: int = 1,
        contradiction_count: int = 0,
    ) -> float:
        score = claim.confidence
        score += min(0.20, evidence_count * 0.03)
        score += min(0.20, source_count * 0.05)
        score -= min(0.40, contradiction_count * 0.20)
        return max(0.0, min(1.0, score))


def _has_negation(text: str) -> bool:
    normalized = f" {normalize_text_key(text)} "
    return any(f" {marker} " in normalized for marker in NEGATION_MARKERS)


def _strip_negation(text: str) -> str:
    normalized = f" {normalize_text_key(text)} "
    for marker in NEGATION_MARKERS:
        normalized = normalized.replace(f" {marker} ", " ")
    return " ".join(normalized.split())


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _source_count(*claims: ClaimMemory) -> int:
    sources: set[str] = set()
    for claim in claims:
        for key in ("source_id", "source_name"):
            value = claim.metadata.get(key)
            if value:
                sources.add(str(value))
        sources.update(str(item).split(":", 1)[0] for item in claim.evidence_ids if item)
    return max(1, len(sources))


def min_dt(*values: datetime) -> datetime:
    normalized = [_ensure_utc(value) for value in values]
    return min(normalized)


def max_dt(*values: datetime) -> datetime:
    normalized = [_ensure_utc(value) for value in values]
    return max(normalized)


def _ensure_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = [
    "ClaimConsolidationAction",
    "ClaimConsolidationResult",
    "ClaimConsolidator",
    "NEGATION_MARKERS",
]
