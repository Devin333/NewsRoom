from __future__ import annotations

from backend.research.method_graph import MethodGraph, MethodGraphEdge, ResearchMethod, validate_method_edge_evidence


def test_method_graph_relations_are_serializable_and_deduped() -> None:
    method = ResearchMethod(
        method_id="harness_control",
        name="Harness Control",
        paper_id="paper-1",
        source_refs=["paper://paper-1/sec-method"],
    )
    edge = MethodGraphEdge(
        edge_id="edge-1",
        source_id=method.method_id,
        target_id="benchmark:mmlu",
        relation_type="evaluates_on",
        paper_id="paper-1",
        evidence_refs=["paper://paper-1/sec-exp"],
    )
    graph = MethodGraph(graph_id="graph-1", methods=[method], edges=[edge, edge])

    assert len(graph.edges) == 1
    assert graph.to_dict()["edges"][0]["relation_type"] == "evaluates_on"
    assert validate_method_edge_evidence(edge).passed is True
