from datetime import UTC, datetime

from business.memory.graph_models import GraphEdge, GraphExpansion, GraphNode, GraphPath, GraphQuery


def test_graph_models_serialize_and_report_path_length() -> None:
    now = datetime(2026, 5, 22, tzinfo=UTC)
    entity = GraphNode("entity-1", "entity", "OpenAI", score=0.8, created_at=now)
    event = GraphNode("event-1", "event", "Launch", metadata={"topic": "AI"})
    edge = GraphEdge("edge-1", "event-1", "entity-1", "involves", confidence=0.9, valid_at=now)
    path = GraphPath(nodes=[event, entity], edges=[edge], score=0.9)
    expansion = GraphExpansion(root=entity, nodes=[event], edges=[edge], depth=1)
    query = GraphQuery(node_type="entity", depth=2, metadata={"query": "OpenAI"})

    assert entity.to_dict()["created_at"] == "2026-05-22T00:00:00+00:00"
    assert edge.is_active() is True
    assert path.length() == 1
    assert expansion.to_dict()["root"]["node_id"] == "entity-1"
    assert query.metadata["query"] == "OpenAI"
