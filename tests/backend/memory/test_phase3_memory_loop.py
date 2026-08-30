from backend.agents import HistorianAgent, HistorianAgentInput
from backend.memory.evaluation import MemoryEvaluationRequest, MemoryEvaluator
from backend.memory.feedback_memory import FeedbackMemory, FeedbackMemoryService
from backend.memory.graph_memory import GraphMemoryService
from backend.memory.historical_context import HistoricalContextService
from backend.memory.intelligence_context import IntelligenceMemoryContext
from backend.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory
from backend.memory.policy_learning import MemoryPolicyLearningService
from backend.memory.timeline_service import TimelineService
from infrastructure.storage.graph import PostgresGraphMemoryStore


def test_phase3_memory_loop_connects_graph_historian_evaluation_policy_and_feedback() -> None:
    repository = _Phase3Repository()

    graph_service = GraphMemoryService(PostgresGraphMemoryStore(repository))
    historical_service = HistoricalContextService(
        recall_service=_RecallService(repository),
        timeline_service=TimelineService(repository),
        graph_service=graph_service,
    )
    historian = HistorianAgent(historical_service)

    historian_output = historian.analyze(HistorianAgentInput(topic="AI"))
    assert historian_output.summary
    assert historian_output.contradictions

    expansion = graph_service.expand_entity("entity-openai", depth=2)
    assert expansion.nodes

    report = MemoryEvaluator(repository).evaluate(MemoryEvaluationRequest(topic="AI", limit=10))
    assert report.metrics.overall_score() >= 0.0

    proposals = MemoryPolicyLearningService().propose_updates(report)
    assert isinstance(proposals, list)

    feedback_result = FeedbackMemoryService(repository).ingest_feedback(
        FeedbackMemory(
            feedback_id="fb-1",
            feedback_type="source_block",
            target_type="source",
            target_id="source-1",
            content="too noisy",
        )
    )
    assert feedback_result.preference_ids
    assert repository.preferences


class _RecallService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def recall_for_topic(self, topic, *, limit=8):
        return IntelligenceMemoryContext(
            query=topic,
            topic=topic,
            claims=list(self.repository.claims),
            events=list(self.repository.events),
            evidence=list(self.repository.evidence),
            conflicts=[{"claim_id": "claim-2", "message": "conflict"}],
            metadata={"memory_available": True},
        )


class _Phase3Repository:
    entity = EntityMemory(
        entity_id="entity-openai",
        entity_type="organization",
        canonical_name="OpenAI",
        importance_score=0.9,
    )
    evidence = [
        EvidenceMemory(
            evidence_id="ev-1",
            run_id="run-1",
            title="Evidence",
            summary="Evidence summary",
            source_urls=["https://example.com"],
            source_item_ids=["item-1"],
            source_id="source-1",
            topic="AI",
            confidence=0.9,
        )
    ]
    claims = [
        ClaimMemory(claim_id="claim-1", run_id="run-1", text="Supported claim", evidence_ids=["ev-1"]),
        ClaimMemory(claim_id="claim-2", run_id="run-1", text="Contradicted claim", status="contradicted"),
    ]
    events = [
        EventMemory(
            event_id="event-1",
            event_type="general_news",
            title="AI event",
            summary="AI event summary",
            run_id="run-1",
            topic="AI",
            entity_ids=["entity-openai"],
            claim_ids=["claim-1", "claim-2"],
            evidence_ids=["ev-1"],
        )
    ]

    def __init__(self) -> None:
        self.preferences = []
        self.decisions = []

    def get_entity(self, entity_id):
        return self.entity if entity_id == self.entity.entity_id else None

    def get_event(self, event_id):
        return self.events[0] if event_id == self.events[0].event_id else None

    def get_claim(self, claim_id):
        return next((claim for claim in self.claims if claim.claim_id == claim_id), None)

    def list_events_by_entity(self, entity_id, *, limit=20):
        return list(self.events)

    def list_claims_by_entity(self, entity_id, *, limit=20):
        return list(self.claims)

    def list_claims_by_topic(self, topic, *, limit=20):
        return list(self.claims)

    def list_events_by_topic(self, topic, *, limit=20):
        return list(self.events)

    def list_evidence_for_claim(self, claim_id):
        return list(self.evidence) if claim_id == "claim-1" else []

    def list_decisions_for_target(self, target_type, target_id, *, limit=20):
        return []

    def search_entities(self, *, query, topic=None, limit=8):
        return [self.entity]

    def search_claims(self, *, query, topic=None, limit=8):
        return list(self.claims)

    def search_events(self, *, query, topic=None, limit=8):
        return list(self.events)

    def search_evidence(self, *, query, topic=None, limit=8):
        return list(self.evidence)

    def search_decisions(self, *, query, topic=None, limit=8):
        return []

    def search_preferences(self, *, query, topic=None, limit=8):
        return []

    def find_similar_events(self, event, *, limit=3):
        return []

    def save_preferences(self, preferences):
        self.preferences.extend(preferences)

    def save_decisions(self, decisions):
        self.decisions.extend(decisions)
