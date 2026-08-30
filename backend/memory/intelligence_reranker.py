from __future__ import annotations

from dataclasses import dataclass

from backend.memory.intelligence_models import ClaimMemory, EventMemory, EvidenceMemory


@dataclass(frozen=True)
class MemoryRerankFeatures:
    vector_score: float = 0.0
    freshness_score: float = 0.0
    source_reliability_score: float = 0.0
    topic_match_score: float = 0.0
    entity_match_score: float = 0.0
    duplicate_penalty: float = 0.0
    contradiction_penalty: float = 0.0

    def final_score(self) -> float:
        score = (
            self.vector_score * 0.35
            + self.freshness_score * 0.15
            + self.source_reliability_score * 0.20
            + self.topic_match_score * 0.20
            + self.entity_match_score * 0.10
            - self.duplicate_penalty * 0.20
            - self.contradiction_penalty * 0.30
        )
        return _clamp(score)


class IntelligenceMemoryReranker:
    def score_evidence(self, item: EvidenceMemory, *, query: str, topic: str | None = None) -> float:
        return MemoryRerankFeatures(
            vector_score=_text_overlap(query, item.to_index_text()),
            source_reliability_score=item.confidence,
            topic_match_score=_topic_match(topic, item.topic),
        ).final_score()

    def score_claim(self, claim: ClaimMemory, *, query: str, topic: str | None = None) -> float:
        del topic
        return MemoryRerankFeatures(
            vector_score=_text_overlap(query, claim.text),
            source_reliability_score=claim.confidence,
            contradiction_penalty=1.0 if claim.status == "contradicted" else 0.0,
        ).final_score()

    def score_event(self, event: EventMemory, *, query: str, topic: str | None = None) -> float:
        return MemoryRerankFeatures(
            vector_score=_text_overlap(query, event.to_index_text()),
            topic_match_score=_topic_match(topic, event.topic),
            entity_match_score=min(1.0, event.entity_count() / 5.0),
        ).final_score()


def _text_overlap(query: str, text: str) -> float:
    query_terms = {term for term in query.casefold().split() if term}
    if not query_terms:
        return 0.0
    text_terms = {term for term in text.casefold().split() if term}
    return _clamp(len(query_terms & text_terms) / len(query_terms))


def _topic_match(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return 1.0 if left.casefold() == right.casefold() else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = ["IntelligenceMemoryReranker", "MemoryRerankFeatures"]
