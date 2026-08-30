from backend.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory
from backend.memory.intelligence_recall import IntelligenceMemoryRecallService, RecallPlan
from backend.memory.intelligence_reranker import IntelligenceMemoryReranker, MemoryRerankFeatures


def test_recall_without_repository_returns_empty_context() -> None:
    context = IntelligenceMemoryRecallService().recall(RecallPlan(query="AI", topic="AI"))

    assert context.is_empty()
    assert context.query == "AI"
    assert context.topic == "AI"
    assert context.metadata["memory_available"] is False


def test_recall_uses_repository_when_available() -> None:
    context = IntelligenceMemoryRecallService(_FakeQueryRepository()).recall_for_topic("AI", limit=3)

    assert not context.is_empty()
    assert context.evidence[0].evidence_id == "ev-1"
    assert context.metadata["memory_available"] is True
    assert "Known claims:" in context.to_prompt_context()
    assert "Recent timeline:" in context.to_prompt_context()


def test_recall_query_detects_claim_conflicts() -> None:
    context = IntelligenceMemoryRecallService(_FakeQueryRepository()).recall_query(
        "check claim",
        topic="AI",
        claim_text="OpenAI released a model",
    )

    assert context.metadata["intent"] == "claim_check"
    assert context.conflicts
    assert "Conflicts / warnings:" in context.to_prompt_context()


def test_reranker_scores_are_clamped() -> None:
    assert MemoryRerankFeatures(vector_score=10.0).final_score() == 1.0
    score = IntelligenceMemoryReranker().score_evidence(
        EvidenceMemory(
            evidence_id="ev-1",
            run_id="run-1",
            title="AI memory",
            summary="Memory recall",
            source_urls=[],
            source_item_ids=[],
            confidence=0.9,
            topic="AI",
        ),
        query="AI recall",
        topic="AI",
    )

    assert 0.0 < score <= 1.0


class _FakeQueryRepository:
    def search_evidence(self, *, query, topic=None, limit=8):
        return [
            EvidenceMemory(
                evidence_id="ev-1",
                run_id="run-1",
                title=query,
                summary=topic or "",
                source_urls=[],
                source_item_ids=[],
            )
        ][:limit]

    def search_claims(self, *, query, topic=None, limit=8):
        return [
            ClaimMemory(
                claim_id="claim-1",
                run_id="run-1",
                text="OpenAI released a model",
                subject_entity_id="entity-openai",
                predicate="released",
                evidence_ids=["ev-1"],
            ),
            ClaimMemory(
                claim_id="claim-2",
                run_id="run-2",
                text="OpenAI did not release a model",
                subject_entity_id="entity-openai",
                predicate="released",
                evidence_ids=["ev-2"],
            ),
        ][:limit]

    def search_entities(self, *, query, topic=None, limit=8):
        return [EntityMemory(entity_id="entity-openai", entity_type="organization", canonical_name="OpenAI")][:limit]

    def search_events(self, *, query, topic=None, limit=8):
        return [
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="AI update",
                summary="Summary",
                run_id="run-1",
                topic=topic,
            )
        ][:limit]

    def search_decisions(self, *, query, topic=None, limit=8):
        return []

    def search_preferences(self, *, query, topic=None, limit=8):
        return []

    def list_claims_by_topic(self, topic, *, limit=20):
        return self.search_claims(query=topic, topic=topic, limit=limit)

    def find_similar_claims(self, claim, *, limit=10):
        return self.search_claims(query=claim.text, limit=limit)

    def list_events_by_topic(self, topic, *, limit=20):
        return self.search_events(query=topic, topic=topic, limit=limit)

    def list_evidence_for_claim(self, claim_id):
        return self.search_evidence(query=claim_id)

    def find_entity_by_name(self, name):
        return EntityMemory(entity_id="entity-openai", entity_type="organization", canonical_name=name)
