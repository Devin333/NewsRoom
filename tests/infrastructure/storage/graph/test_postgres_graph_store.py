from business.memory.graph_models import GraphQuery
from business.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory
from infrastructure.storage.graph import PostgresGraphMemoryStore


def test_postgres_graph_store_expands_entity_to_events_claims_and_evidence() -> None:
    store = PostgresGraphMemoryStore(_GraphRepository())

    expansion = store.neighbors("entity-openai", depth=2)

    node_ids = {node.node_id for node in expansion.nodes}
    edge_types = {edge.edge_type for edge in expansion.edges}
    assert {"event-1", "claim-1", "ev-1"}.issubset(node_ids)
    assert {"involves", "has_claim", "supported_by"}.issubset(edge_types)
    assert expansion.root.label == "OpenAI"


def test_postgres_graph_store_finds_path_between_entity_and_evidence() -> None:
    store = PostgresGraphMemoryStore(_GraphRepository())

    paths = store.paths_between("entity-openai", "ev-1", max_depth=3)

    assert paths
    assert paths[0].nodes[0].node_id == "entity-openai"
    assert paths[0].nodes[-1].node_id == "ev-1"
    assert paths[0].length() <= 3


def test_postgres_graph_store_searches_nodes_by_type() -> None:
    store = PostgresGraphMemoryStore(_GraphRepository())

    nodes = store.search_nodes(GraphQuery(node_type="event", metadata={"query": "memory", "topic": "AI"}))

    assert nodes[0].node_type == "event"
    assert nodes[0].label == "OpenAI ships memory"


class _GraphRepository:
    entity = EntityMemory(
        entity_id="entity-openai",
        entity_type="organization",
        canonical_name="OpenAI",
        importance_score=0.9,
        trend_score=0.7,
    )
    event = EventMemory(
        event_id="event-1",
        event_type="model_release",
        title="OpenAI ships memory",
        summary="OpenAI shipped memory for agents.",
        run_id="run-1",
        topic="AI",
        entity_ids=["entity-openai"],
        claim_ids=["claim-1"],
        evidence_ids=["ev-1"],
        impact_score=0.8,
        novelty_score=0.6,
    )
    claim = ClaimMemory(
        claim_id="claim-1",
        run_id="run-1",
        text="OpenAI shipped memory for agents.",
        evidence_ids=["ev-1"],
    )
    evidence = EvidenceMemory(
        evidence_id="ev-1",
        run_id="run-1",
        title="OpenAI ships memory",
        summary="Evidence summary",
        source_urls=["https://example.com"],
        source_item_ids=["item-1"],
        topic="AI",
        source_id="source-1",
    )

    def get_entity(self, entity_id):
        return self.entity if entity_id == self.entity.entity_id else None

    def get_event(self, event_id):
        return self.event if event_id == self.event.event_id else None

    def get_claim(self, claim_id):
        return self.claim if claim_id == self.claim.claim_id else None

    def list_events_by_entity(self, entity_id, *, limit=20):
        return [self.event] if entity_id == "entity-openai" else []

    def list_claims_by_entity(self, entity_id, *, limit=20):
        return [self.claim] if entity_id == "entity-openai" else []

    def list_evidence_for_claim(self, claim_id):
        return [self.evidence] if claim_id == "claim-1" else []

    def search_evidence(self, *, query, topic=None, limit=8):
        return [self.evidence] if query in {"ev-1", "memory"} or not query else []

    def search_decisions(self, *, query, topic=None, limit=8):
        return []

    def search_preferences(self, *, query, topic=None, limit=8):
        return []

    def search_events(self, *, query, topic=None, limit=8):
        return [self.event]

    def search_entities(self, *, query, topic=None, limit=8):
        return [self.entity]

    def search_claims(self, *, query, topic=None, limit=8):
        return [self.claim]
