from business.memory.graph_memory import GraphMemoryService
from business.memory.graph_models import GraphEdge, GraphExpansion, GraphNode, GraphPath
from interfaces.services import graph_memory_service as graph_memory_service_module
from interfaces.services.graph_memory_service import GraphMemoryApplicationService, graph_memory_service_from_env


def test_graph_memory_application_service_serializes_expansion_paths_and_search() -> None:
    service = GraphMemoryApplicationService(GraphMemoryService(_GraphStore()))

    expansion = service.expand_entity("entity-1").to_dict()
    paths = service.paths_between("entity-1", "claim-1").to_dict()
    search = service.search_nodes(query="OpenAI", node_type="entity")

    assert expansion["target_id"] == "entity-1"
    assert expansion["expansion"]["root"]["node_id"] == "entity-1"
    assert paths["paths"][0]["nodes"][-1]["node_id"] == "claim-1"
    assert search["nodes"][0]["label"] == "OpenAI"


def test_graph_memory_service_from_env_returns_none_without_repository() -> None:
    assert graph_memory_service_from_env(env={}) is None


def test_graph_memory_service_from_env_builds_with_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        graph_memory_service_module,
        "_build_intelligence_repository_from_env",
        lambda *, env=None: _Repository(),
    )

    service = graph_memory_service_from_env(env={"NEWS_MEMORY_POSTGRES_ENABLED": "true"})

    assert isinstance(service, GraphMemoryApplicationService)


class _Repository:
    pass


class _GraphStore:
    root = GraphNode(node_id="entity-1", node_type="entity", label="OpenAI")
    claim = GraphNode(node_id="claim-1", node_type="claim", label="Claim")
    edge = GraphEdge(edge_id="edge-1", source_id="entity-1", target_id="claim-1", edge_type="related_to")

    def get_node(self, node_id):
        return self.root if node_id == "entity-1" else self.claim

    def neighbors(self, node_id, *, depth=1, edge_types=None, limit=50):
        return GraphExpansion(root=self.root, nodes=[self.claim], edges=[self.edge], depth=depth)

    def paths_between(self, source_id, target_id, *, max_depth=3, limit=10):
        return [GraphPath(nodes=[self.root, self.claim], edges=[self.edge], score=1.0)]

    def search_nodes(self, query):
        return [self.root]
