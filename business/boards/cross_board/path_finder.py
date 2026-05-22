from __future__ import annotations

from typing import Any

from business.boards.cross_board.evidence_chain import CrossBoardEvidenceChainBuilder
from business.boards.cross_board.graph_models import CrossBoardGraph, CrossBoardPath, CrossBoardPathSearchRequest, CrossBoardPathSearchResult
from business.boards.cross_board.path_scorer import CrossBoardPathScoringService
from business.boards.cross_board.regression_guard import ORDERED_STAGE_TYPES, guard_cross_board_path
from business.foundation import ObjectRef, build_stable_id


class CrossBoardPathFinder:
    def __init__(self, path_scoring_service: CrossBoardPathScoringService | None = None) -> None:
        self.path_scoring_service = path_scoring_service or CrossBoardPathScoringService()

    def find_paths(self, graph: CrossBoardGraph, request: CrossBoardPathSearchRequest | None = None) -> CrossBoardPathSearchResult:
        request = request or CrossBoardPathSearchRequest()
        requested_ids = {ref.object_id for ref in request.technology_refs}
        technology_refs = _technology_refs(graph)
        if requested_ids:
            technology_refs = [ref for ref in technology_refs if ref.object_id in requested_ids]
        paths: list[CrossBoardPath] = []
        for technology_ref in technology_refs:
            edges = [edge for edge in graph.edges if edge.target_ref.object_id == technology_ref.object_id and edge.stage_type in ORDERED_STAGE_TYPES]
            if not edges:
                continue
            path_edges = _best_edges_by_stage(edges)
            chain = CrossBoardEvidenceChainBuilder().build(path_edges)
            missing = [stage for stage in ORDERED_STAGE_TYPES if stage not in {edge.stage_type for edge in path_edges}]
            board_sequence = [edge.board_type.value for edge in path_edges if edge.board_type is not None]
            confidence = chain.min_relation_confidence
            ordered_nodes = [node for edge in path_edges for node in _nodes_for_edge(graph, edge)]
            path = CrossBoardPath(
                path_id=build_stable_id("cross_path", technology_ref.object_id, [edge.relation_id for edge in path_edges]),
                technology_ref=technology_ref,
                ordered_nodes=_dedupe_nodes(ordered_nodes),
                ordered_edges=path_edges,
                evidence_relation_ids=[edge.relation_id for edge in path_edges],
                evidence_chain_refs=[chain.chain_id],
                board_sequence=board_sequence,
                confidence=confidence,
                path_score=0.0,
                missing_stage_types=missing,
                duplicate_evidence_count=chain.duplicate_evidence_count,
                contradictory_evidence_count=chain.contradictory_evidence_count,
                evidence_chain=chain,
                metadata={"stage_types": [edge.stage_type for edge in path_edges]},
            )
            guard = guard_cross_board_path(path)
            guarded_path = path.model_copy(
                update={
                    "quality_checks": guard.checks,
                    "blocking_reasons": guard.blocking_reasons,
                    "guard_result": guard,
                }
            )
            paths.append(self.path_scoring_service.score_path(guarded_path))
        paths.sort(key=lambda path: (path.path_score, path.confidence, len(path.evidence_relation_ids)), reverse=True)
        return CrossBoardPathSearchResult(
            graph=graph,
            paths=paths[: request.limit],
            metadata={"requested_technology_count": len(request.technology_refs)},
        )


def _technology_refs(graph: CrossBoardGraph) -> list[ObjectRef]:
    refs: dict[str, ObjectRef] = {}
    for node in graph.nodes:
        object_type = _object_type_value(node.object_ref.object_type)
        if object_type == "technology":
            refs[node.object_ref.object_id] = node.object_ref
    return sorted(refs.values(), key=lambda ref: ref.object_id)


def _best_edges_by_stage(edges):
    result = []
    for stage in ORDERED_STAGE_TYPES:
        stage_edges = [edge for edge in edges if edge.stage_type == stage]
        if not stage_edges:
            continue
        result.append(sorted(stage_edges, key=lambda edge: (edge.confidence.value, edge.relation_id), reverse=True)[0])
    return result


def _nodes_for_edge(graph: CrossBoardGraph, edge):
    lookup = {node.node_id: node for node in graph.nodes}
    return [node for node in (lookup.get(edge.source_node_id), lookup.get(edge.target_node_id)) if node is not None]


def _dedupe_nodes(nodes):
    seen: set[str] = set()
    result = []
    for node in nodes:
        if node.node_id in seen:
            continue
        seen.add(node.node_id)
        result.append(node)
    return result


def _object_type_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


__all__ = ["CrossBoardPathFinder"]
