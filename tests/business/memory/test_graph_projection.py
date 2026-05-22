import pytest

from business.memory.graph_memory import GraphMemoryService
from business.memory.graph_models import GraphEdge, GraphExpansion, GraphNode
from business.memory.graph_projection import GraphProjectionRequest, GraphProjectionService


def test_graph_projection_summarizes_entity_expansion() -> None:
    service = GraphProjectionService(GraphMemoryService(_GraphStore()))

    summary = service.summarize_entity_projection(GraphProjectionRequest(entity_id="entity-1"))

    assert summary.root_id == "entity-1"
    assert summary.node_count == 3
    assert summary.edge_count == 2
    assert summary.node_types == {"entity": 1, "event": 1, "claim": 1}
    assert summary.edge_types == {"involves": 1, "has_claim": 1}
    assert summary.to_dict()["metadata"]["store"] == "fake"


def test_graph_projection_requires_entity_id() -> None:
    service = GraphProjectionService(GraphMemoryService(_GraphStore()))

    with pytest.raises(ValueError, match="entity_id is required"):
        service.summarize_entity_projection(GraphProjectionRequest())


class _GraphStore:
    def get_node(self, node_id):
        return GraphNode(node_id=node_id, node_type="entity", label="OpenAI")

    def neighbors(self, node_id, *, depth=1, edge_types=None, limit=50):
        root = self.get_node(node_id)
        event = GraphNode(node_id="event-1", node_type="event", label="Event")
        claim = GraphNode(node_id="claim-1", node_type="claim", label="Claim")
        return GraphExpansion(
            root=root,
            nodes=[event, claim],
            edges=[
                GraphEdge(edge_id="e1", source_id="event-1", target_id=node_id, edge_type="involves"),
                GraphEdge(edge_id="e2", source_id="event-1", target_id="claim-1", edge_type="has_claim"),
            ],
            depth=depth,
            metadata={"store": "fake"},
        )

    def paths_between(self, source_id, target_id, *, max_depth=3, limit=10):
        return []

    def search_nodes(self, query):
        return []
