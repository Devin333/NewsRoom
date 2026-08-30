from __future__ import annotations

from backend.foundation import Confidence, Entity, ObjectRef, RelationType, Signal
from backend.layers.extraction.models import ExtractionResult
from backend.layers.relation.pipeline import RelationCandidate


def mention_candidates(signal: Signal, extraction: ExtractionResult) -> list[RelationCandidate]:
    signal_ref = ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)
    candidates: list[RelationCandidate] = []
    for entity in extraction.entities:
        candidates.append(
            RelationCandidate(
                relation_type=RelationType.MENTIONS,
                source_ref=signal_ref,
                target_ref=ObjectRef(
                    object_type=object_type_from_entity(entity),
                    object_id=entity.entity_id,
                    label=entity.canonical_name,
                ),
                evidence_signal_ids=[signal.signal_id],
                evidence_claim_ids=[],
                raw_reason="entity mention from entity extractor",
                confidence=Confidence(value=max(0.5, entity.confidence.value), factors=list(entity.confidence.factors), reason="entity mention confidence", evidence_count=1),
                metadata={"linker": "MentionLinker", "entity_type": entity.entity_type.value},
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
                raw_reason="topic classification relation",
                confidence=Confidence(value=max(0.5, topic.confidence.value), factors=list(topic.confidence.factors), reason="topic relation confidence", evidence_count=1),
                metadata={"linker": "MentionLinker", "topic_key": topic.normalized_key},
            )
        )
    return candidates


def technology_candidates(signal: Signal, extraction: ExtractionResult, relation_type: RelationType, linker_name: str) -> list[RelationCandidate]:
    candidates: list[RelationCandidate] = []
    for technology in extraction.technologies:
        candidates.append(
            RelationCandidate(
                relation_type=relation_type,
                source_ref=source_ref(signal),
                target_ref=ObjectRef(
                    object_type="technology",
                    object_id=technology.technology_id,
                    label=technology.name,
                ),
                evidence_signal_ids=[signal.signal_id],
                evidence_claim_ids=[
                    claim.claim_id for claim in extraction.claims if claim.object_ref and claim.object_ref.object_id == technology.technology_id
                ],
                raw_reason=f"{signal.signal_type.value} {relation_type.value} relation",
                confidence=Confidence(value=max(0.55, technology.confidence.value), factors=list(technology.confidence.factors), reason=f"{linker_name} technology confidence", evidence_count=1),
                metadata={"linker": linker_name, "technology_category": technology.category.value},
            )
        )
    return candidates


def claim_predicate_candidates(signal: Signal, extraction: ExtractionResult, predicate: str, relation_type: RelationType, linker_name: str) -> list[RelationCandidate]:
    candidates: list[RelationCandidate] = []
    signal_ref = ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)
    for claim in extraction.claims:
        if claim.object_ref is None or claim.predicate != predicate:
            continue
        candidates.append(
            RelationCandidate(
                relation_type=relation_type,
                source_ref=claim.subject_ref or signal_ref,
                target_ref=claim.object_ref,
                evidence_signal_ids=[signal.signal_id],
                evidence_claim_ids=[claim.claim_id],
                raw_reason=f"{predicate} claim relation",
                confidence=Confidence(value=max(0.55, claim.confidence.value), factors=list(claim.confidence.factors), reason=f"{predicate} claim confidence", evidence_count=1),
                metadata={"linker": linker_name, "claim_predicate": predicate},
            )
        )
    return candidates


def compare_candidates(signals: list[Signal], extraction_results: list[ExtractionResult]) -> list[RelationCandidate]:
    by_technology: dict[str, list[tuple[Signal, ExtractionResult]]] = {}
    for signal, extraction in zip(signals, extraction_results):
        for technology in extraction.technologies:
            by_technology.setdefault(technology.technology_id, []).append((signal, extraction))
    candidates: list[RelationCandidate] = []
    for technology_id, items in by_technology.items():
        if len(items) < 2:
            continue
        first_signal, first_extraction = items[0]
        second_signal, _second_extraction = items[1]
        technology = next(tech for tech in first_extraction.technologies if tech.technology_id == technology_id)
        candidates.append(
            RelationCandidate(
                relation_type=RelationType.COMPARES,
                source_ref=source_ref(first_signal),
                target_ref=source_ref(second_signal),
                evidence_signal_ids=[first_signal.signal_id, second_signal.signal_id],
                evidence_claim_ids=[],
                raw_reason=f"shared technology comparison for {technology.name}",
                confidence=Confidence(value=0.62, factors=[], reason="shared technology compare rule", evidence_count=2),
                metadata={"linker": "CompareLinker", "technology_id": technology_id},
            )
        )
    return candidates


def source_ref(signal: Signal) -> ObjectRef:
    if signal.signal_type.value == "paper":
        return ObjectRef(object_type="paper", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "github_project":
        return ObjectRef(object_type="project", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "community_discussion":
        return ObjectRef(object_type="community_thread", object_id=signal.signal_id, label=signal.title)
    if signal.signal_type.value == "ai_news":
        return ObjectRef(object_type="news_item", object_id=signal.signal_id, label=signal.title)
    return ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)


def object_type_from_entity(entity: Entity) -> str:
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
