from __future__ import annotations

from typing import Any, Iterable

from business.boards.cross_board.graph_models import CrossBoardGraph, CrossBoardGraphEdge, CrossBoardGraphNode
from business.boards.cross_board.regression_guard import board_for_stage_relation, stage_for_relation_type
from business.foundation import ObjectRef, Relation, Signal, build_stable_id


class CrossBoardGraphBuilder:
    def build(
        self,
        *,
        signals: list[Signal] | None = None,
        extraction_results: list[Any] | None = None,
        relations: list[Relation] | None = None,
        analysis: Any | None = None,
        board_outputs: dict[str, Any] | None = None,
    ) -> CrossBoardGraph:
        signals = signals or []
        extraction_results = extraction_results or []
        relations = relations or []
        nodes: dict[str, CrossBoardGraphNode] = {}
        edges: list[CrossBoardGraphEdge] = []
        signal_lookup = {signal.signal_id: signal for signal in signals}

        for technology_ref in _technology_refs(extraction_results, relations, analysis):
            nodes[_node_key(technology_ref)] = CrossBoardGraphNode(
                node_id=_node_key(technology_ref),
                object_ref=technology_ref,
                label=technology_ref.label or technology_ref.object_id,
                metadata={"node_kind": "technology"},
            )

        for relation in relations:
            stage_type = stage_for_relation_type(relation.relation_type)
            board_type = board_for_stage_relation(relation.relation_type)
            if stage_type is None:
                continue
            source_node_id = _node_key(relation.source_ref)
            target_node_id = _node_key(relation.target_ref)
            if source_node_id not in nodes:
                nodes[source_node_id] = CrossBoardGraphNode(
                    node_id=source_node_id,
                    object_ref=relation.source_ref,
                    board_type=board_type,
                    stage_type=stage_type,
                    label=relation.source_ref.label or relation.source_ref.object_id,
                    metadata={"node_kind": "stage_source"},
                )
            if target_node_id not in nodes:
                nodes[target_node_id] = CrossBoardGraphNode(
                    node_id=target_node_id,
                    object_ref=relation.target_ref,
                    label=relation.target_ref.label or relation.target_ref.object_id,
                    metadata={"node_kind": "technology"},
                )
            edges.append(
                CrossBoardGraphEdge(
                    edge_id=build_stable_id("cross_edge", relation.relation_id, source_node_id, target_node_id),
                    relation_id=relation.relation_id,
                    relation_type=relation.relation_type,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    source_ref=relation.source_ref,
                    target_ref=relation.target_ref,
                    board_type=board_type,
                    stage_type=stage_type,
                    confidence=relation.confidence,
                    evidence_signal_ids=list(relation.evidence_signal_ids),
                    evidence_claim_ids=list(relation.evidence_claim_ids),
                    evidence_refs=[signal_lookup[signal_id].source for signal_id in relation.evidence_signal_ids if signal_id in signal_lookup],
                    metadata=dict(relation.metadata),
                )
            )

        return CrossBoardGraph(
            graph_id=build_stable_id(
                "cross_graph",
                [node.node_id for node in nodes.values()],
                [edge.relation_id for edge in edges],
            ),
            nodes=sorted(nodes.values(), key=lambda node: node.node_id),
            edges=sorted(edges, key=lambda edge: edge.edge_id),
            metadata={
                "signal_count": len(signals),
                "relation_count": len(relations),
                "board_output_count": len(board_outputs or {}),
            },
        )


def _technology_refs(extraction_results: Iterable[Any], relations: list[Relation], analysis: Any | None) -> list[ObjectRef]:
    refs: dict[str, ObjectRef] = {}
    for result in extraction_results:
        for technology in getattr(result, "technologies", []):
            ref = ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name)
            refs[ref.object_id] = ref
    for relation in relations:
        if str(relation.target_ref.object_type) == "technology":
            refs[relation.target_ref.object_id] = relation.target_ref
    for item in getattr(analysis, "radar_items", []) if analysis is not None else []:
        refs[item.technology_ref.object_id] = item.technology_ref
    return sorted(refs.values(), key=lambda ref: ref.object_id)


def _node_key(ref: ObjectRef) -> str:
    return build_stable_id("cross_node", _object_type_value(ref.object_type), ref.object_id)


def _object_type_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


__all__ = ["CrossBoardGraphBuilder"]
