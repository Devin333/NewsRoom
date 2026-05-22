from business.memory.graph_models import GraphExpansion, GraphNode
from business.memory.graph_memory import GraphMemoryService
from business.memory.historical_context import HistoricalContextRequest, HistoricalContextService
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory, EventMemory
from business.memory.timeline_service import Timeline, TimelineItem


def test_historical_context_service_builds_topic_context() -> None:
    service = HistoricalContextService(
        recall_service=_RecallService(),
        timeline_service=_TimelineService(),
    )

    context = service.build_context(HistoricalContextRequest(topic="AI", limit=5))

    assert context.topic == "AI"
    assert context.known_claims[0].text == "Known claim"
    assert context.contradictions[0].status == "contradicted"
    assert "Timeline summary:" in context.to_prompt_context()


def test_historical_context_service_builds_entity_context_with_graph() -> None:
    service = HistoricalContextService(
        recall_service=_RecallService(),
        timeline_service=_TimelineService(),
        graph_service=GraphMemoryService(_GraphStore()),
    )

    context = service.build_context(HistoricalContextRequest(entity_id="entity-1"))

    assert context.graph_expansion is not None
    assert context.entity is not None
    assert context.recent_events[0].event_id == "event-1"


class _RecallService:
    def recall_for_topic(self, topic, *, limit=8):
        return IntelligenceMemoryContext(
            query=topic,
            topic=topic,
            claims=[
                ClaimMemory(claim_id="claim-1", run_id="run-1", text="Known claim"),
                ClaimMemory(claim_id="claim-2", run_id="run-1", text="Contradicted claim", status="contradicted"),
            ],
            events=[
                EventMemory(
                    event_id="event-1",
                    event_type="general_news",
                    title="AI event",
                    summary="Summary",
                    run_id="run-1",
                    topic=topic,
                )
            ],
            conflicts=[{"claim_id": "claim-2", "message": "conflict"}],
        )


class _TimelineService:
    def get_topic_timeline(self, topic, *, limit=20):
        return Timeline(
            target_type="topic",
            target_id=topic,
            items=[
                TimelineItem(
                    event_id="event-1",
                    title="AI event",
                    summary="Summary",
                    event_type="general_news",
                    event_time=None,
                    detected_at=EventMemory(
                        event_id="tmp",
                        event_type="general_news",
                        title="tmp",
                        summary="tmp",
                        run_id="run",
                    ).detected_at,
                    topic=topic,
                    entity_ids=["entity-1"],
                    claim_ids=["claim-1"],
                    evidence_ids=["ev-1"],
                    impact_score=0.5,
                    novelty_score=0.5,
                )
            ],
        )

    def get_entity_timeline(self, entity_id, *, limit=20):
        return self.get_topic_timeline("AI", limit=limit)


class _GraphStore:
    def get_node(self, node_id):
        return GraphNode(node_id=node_id, node_type="entity", label="OpenAI", metadata={"entity_type": "organization"})

    def neighbors(self, node_id, *, depth=1, edge_types=None, limit=50):
        return GraphExpansion(root=self.get_node(node_id), nodes=[], edges=[], depth=depth)

    def paths_between(self, source_id, target_id, *, max_depth=3, limit=10):
        return []

    def search_nodes(self, query):
        return []
