from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import Field

from business.foundation import (
    Claim,
    Confidence,
    Entity,
    ObjectRef,
    Relation,
    RelationDirection,
    RelationType,
    Signal,
    Technology,
    build_stable_id,
)
from business.layers.extraction.models import ExtractionResult
from business.foundation.primitives import PrimitiveModel


class RelationCandidate(PrimitiveModel):
    relation_type: RelationType
    source_ref: ObjectRef
    target_ref: ObjectRef
    evidence_signal_ids: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    raw_reason: str
    confidence: Confidence
    metadata: dict[str, Any] = Field(default_factory=dict)


class RejectedRelation(PrimitiveModel):
    candidate: RelationCandidate
    reason: str
    detail: str


class RelationPipelineStats(PrimitiveModel):
    candidate_count: int
    accepted_count: int
    rejected_count: int
    by_relation_type: dict[str, int] = Field(default_factory=dict)


class RelationPipelineResult(PrimitiveModel):
    relations: list[Relation] = Field(default_factory=list)
    rejected_candidates: list[RejectedRelation] = Field(default_factory=list)
    stats: RelationPipelineStats


class RelationPipeline:
    def __init__(self, *, linkers: list[Any] | None = None) -> None:
        from business.layers.relation.adopt_linker import AdoptLinker
        from business.layers.relation.compare_linker import CompareLinker
        from business.layers.relation.discuss_linker import DiscussLinker
        from business.layers.relation.implement_linker import ImplementLinker
        from business.layers.relation.mention_linker import MentionLinker
        from business.layers.relation.propose_linker import ProposeLinker

        self.linkers = linkers or [
            MentionLinker(),
            ProposeLinker(),
            ImplementLinker(),
            DiscussLinker(),
            AdoptLinker(),
            CompareLinker(),
        ]

    def run(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        *,
        context: Any | None = None,
    ) -> RelationPipelineResult:
        candidates = self._build_candidates(signals, extraction_results)
        relations: list[Relation] = []
        rejected: list[RejectedRelation] = []
        seen: set[tuple[str, str, str]] = set()
        for candidate in candidates:
            rejection = self._validate(candidate)
            if rejection is not None:
                rejected.append(rejection)
                continue
            dedup_key = (
                candidate.relation_type.value,
                candidate.source_ref.object_id,
                candidate.target_ref.object_id,
            )
            if dedup_key in seen:
                rejected.append(
                    RejectedRelation(
                        candidate=candidate,
                        reason="duplicate_relation",
                        detail="duplicate relation with same source, type, and target",
                    )
                )
                continue
            seen.add(dedup_key)
            relations.append(
                Relation(
                    relation_id=build_stable_id(
                        "rel",
                        candidate.relation_type.value,
                        candidate.source_ref.object_id,
                        candidate.target_ref.object_id,
                    ),
                    relation_type=candidate.relation_type,
                    source_ref=candidate.source_ref,
                    target_ref=candidate.target_ref,
                    direction=self._direction(candidate.relation_type),
                    evidence_signal_ids=list(candidate.evidence_signal_ids),
                    evidence_claim_ids=list(candidate.evidence_claim_ids),
                    confidence=Confidence(
                        value=candidate.confidence.value,
                        factors=list(candidate.confidence.factors),
                        explanation=candidate.confidence.explanation,
                    ),
                    metadata={**candidate.metadata, "raw_reason": candidate.raw_reason},
                )
            )
        stats = RelationPipelineStats(
            candidate_count=len(candidates),
            accepted_count=len(relations),
            rejected_count=len(rejected),
            by_relation_type=dict(Counter(relation.relation_type.value for relation in relations)),
        )
        return RelationPipelineResult(relations=relations, rejected_candidates=rejected, stats=stats)

    def _build_candidates(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
    ) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        for linker in self.linkers:
            candidates.extend(linker.link(signals, extraction_results))
        return candidates

    def _signal_candidates(self, signal: Signal, extraction: ExtractionResult) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        signal_ref = ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)
        for entity in extraction.entities:
            candidates.append(
                RelationCandidate(
                    relation_type=RelationType.MENTIONS,
                    source_ref=signal_ref,
                    target_ref=ObjectRef(
                        object_type=_object_type_from_entity(entity),
                        object_id=entity.entity_id,
                        label=entity.canonical_name,
                    ),
                    evidence_signal_ids=[signal.signal_id],
                    evidence_claim_ids=[],
                    raw_reason="entity mention from extraction",
                    confidence=Confidence(value=max(0.5, entity.confidence.value), factors=list(entity.confidence.factors)),
                )
            )
        for topic in extraction.topics:
            candidates.append(
                RelationCandidate(
                    relation_type=RelationType.SAME_TOPIC,
                    source_ref=signal_ref,
                    target_ref=ObjectRef(object_type="topic", object_id=topic.topic_id, label=topic.name),
                    evidence_signal_ids=[signal.signal_id],
                    evidence_claim_ids=[],
                    raw_reason="topic classification",
                    confidence=Confidence(value=max(0.5, topic.confidence.value), factors=list(topic.confidence.factors)),
                )
            )
        for technology in extraction.technologies:
            relation_type = self._relation_type_for_signal(signal)
            if relation_type is None:
                continue
            candidates.append(
                RelationCandidate(
                    relation_type=relation_type,
                    source_ref=_source_ref(signal, extraction),
                    target_ref=ObjectRef(
                        object_type="technology",
                        object_id=technology.technology_id,
                        label=technology.name,
                    ),
                    evidence_signal_ids=[signal.signal_id],
                    evidence_claim_ids=[
                        claim.claim_id for claim in extraction.claims if claim.object_ref and claim.object_ref.object_id == technology.technology_id
                    ],
                    raw_reason=f"{signal.signal_type.value} relation",
                    confidence=Confidence(value=max(0.55, technology.confidence.value), factors=list(technology.confidence.factors)),
                )
            )
        for claim in extraction.claims:
            if claim.object_ref is None:
                continue
            if claim.predicate == "implements":
                candidates.append(
                    RelationCandidate(
                        relation_type=RelationType.IMPLEMENTS,
                        source_ref=claim.subject_ref or signal_ref,
                        target_ref=claim.object_ref,
                        evidence_signal_ids=[signal.signal_id],
                        evidence_claim_ids=[claim.claim_id],
                        raw_reason="implementation claim",
                        confidence=Confidence(value=max(0.65, claim.confidence.value), factors=list(claim.confidence.factors)),
                    )
                )
            elif claim.predicate == "proposes":
                candidates.append(
                    RelationCandidate(
                        relation_type=RelationType.PROPOSES,
                        source_ref=claim.subject_ref or signal_ref,
                        target_ref=claim.object_ref,
                        evidence_signal_ids=[signal.signal_id],
                        evidence_claim_ids=[claim.claim_id],
                        raw_reason="proposal claim",
                        confidence=Confidence(value=max(0.6, claim.confidence.value), factors=list(claim.confidence.factors)),
                    )
                )
            elif claim.predicate == "adopts":
                candidates.append(
                    RelationCandidate(
                        relation_type=RelationType.ADOPTS,
                        source_ref=claim.subject_ref or signal_ref,
                        target_ref=claim.object_ref,
                        evidence_signal_ids=[signal.signal_id],
                        evidence_claim_ids=[claim.claim_id],
                        raw_reason="adoption claim",
                        confidence=Confidence(value=max(0.65, claim.confidence.value), factors=list(claim.confidence.factors)),
                    )
                )
            elif claim.predicate == "discusses":
                candidates.append(
                    RelationCandidate(
                        relation_type=RelationType.DISCUSSES,
                        source_ref=claim.subject_ref or signal_ref,
                        target_ref=claim.object_ref,
                        evidence_signal_ids=[signal.signal_id],
                        evidence_claim_ids=[claim.claim_id],
                        raw_reason="community discussion claim",
                        confidence=Confidence(value=max(0.55, claim.confidence.value), factors=list(claim.confidence.factors)),
                    )
                )
        return candidates

    def _validate(self, candidate: RelationCandidate) -> RejectedRelation | None:
        relation_rule = _RELATION_RULES[candidate.relation_type.value]
        if not candidate.evidence_signal_ids:
            return RejectedRelation(candidate=candidate, reason="missing_evidence", detail="evidence_signal_ids is required")
        if candidate.confidence.value < relation_rule["min_confidence"]:
            return RejectedRelation(
                candidate=candidate,
                reason="low_confidence",
                detail=f"confidence {candidate.confidence.value} below minimum {relation_rule['min_confidence']}",
            )
        if relation_rule["direction"] == "directed" and candidate.relation_type in {RelationType.COMPARES, RelationType.SIMILAR_TO}:
            return RejectedRelation(
                candidate=candidate,
                reason="invalid_direction",
                detail=f"{candidate.relation_type.value} must be undirected",
            )
        if relation_rule["direction"] == "undirected" and candidate.relation_type not in {RelationType.COMPARES, RelationType.SIMILAR_TO}:
            return RejectedRelation(
                candidate=candidate,
                reason="invalid_direction",
                detail=f"{candidate.relation_type.value} must be directed",
            )
        return None

    def _direction(self, relation_type: RelationType) -> RelationDirection:
        if relation_type in {RelationType.COMPARES, RelationType.SIMILAR_TO}:
            return RelationDirection.UNDIRECTED
        return RelationDirection.DIRECTED

    def _relation_type_for_signal(self, signal: Signal) -> RelationType | None:
        if signal.signal_type.value == "paper":
            return RelationType.PROPOSES
        if signal.signal_type.value == "github_project":
            return RelationType.IMPLEMENTS
        if signal.signal_type.value == "community_discussion":
            return RelationType.DISCUSSES
        if signal.signal_type.value == "ai_news":
            return RelationType.ADOPTS
        return None


_RELATION_RULES: dict[str, dict[str, Any]] = {
    "mentions": {"min_confidence": 0.5, "direction": "directed"},
    "proposes": {"min_confidence": 0.6, "direction": "directed"},
    "implements": {"min_confidence": 0.65, "direction": "directed"},
    "discusses": {"min_confidence": 0.55, "direction": "directed"},
    "compares": {"min_confidence": 0.6, "direction": "undirected"},
    "adopts": {"min_confidence": 0.65, "direction": "directed"},
    "supports": {"min_confidence": 0.55, "direction": "directed"},
    "criticizes": {"min_confidence": 0.55, "direction": "directed"},
    "extends": {"min_confidence": 0.6, "direction": "directed"},
    "similar_to": {"min_confidence": 0.55, "direction": "undirected"},
    "same_topic": {"min_confidence": 0.5, "direction": "directed"},
}


def _source_ref(signal: Signal, extraction: ExtractionResult) -> ObjectRef:
    if signal.signal_type.value == "paper":
        return ObjectRef(object_type="paper", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "github_project":
        return ObjectRef(object_type="project", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "community_discussion":
        return ObjectRef(object_type="community_thread", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "ai_news":
        return ObjectRef(object_type="news_item", object_id=signal.signal_id, label=signal.title)
    return ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)


def _object_type_from_entity(entity: Entity) -> str:
    mapping = {
        "company": "entity",
        "product": "entity",
        "model": "entity",
        "framework": "entity",
        "library": "entity",
        "github_project": "project",
        "paper": "paper",
        "organization": "entity",
        "author": "entity",
        "benchmark": "entity",
        "dataset": "entity",
        "community": "community_thread",
        "person": "entity",
        "unknown": "entity",
    }
    return mapping.get(entity.entity_type.value, "entity")
