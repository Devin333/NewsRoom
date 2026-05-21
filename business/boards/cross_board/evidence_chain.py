from __future__ import annotations

from collections import Counter

from business.boards.cross_board.graph_models import CrossBoardEvidenceChain, CrossBoardGraphEdge
from business.boards.cross_board.regression_guard import ORDERED_STAGE_TYPES
from business.foundation import build_stable_id


class CrossBoardEvidenceChainBuilder:
    def build(self, edges: list[CrossBoardGraphEdge]) -> CrossBoardEvidenceChain:
        relation_ids = [edge.relation_id for edge in edges]
        evidence_ids = _evidence_ids(edges)
        confidences = [edge.confidence.value for edge in edges]
        board_support: dict[str, list[str]] = {}
        for edge in edges:
            if edge.board_type is None:
                continue
            board_support.setdefault(edge.board_type.value, []).append(edge.relation_id)
        return CrossBoardEvidenceChain(
            chain_id=build_stable_id("evidence_chain", relation_ids, evidence_ids),
            evidence_count=len(set(evidence_ids or relation_ids)),
            board_support_count=len(board_support),
            min_relation_confidence=round(min(confidences), 4) if confidences else 0.0,
            average_relation_confidence=round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
            duplicate_evidence_count=_duplicate_count(evidence_ids),
            contradictory_evidence_count=_contradictory_count(edges),
            missing_stage_count=_missing_stage_count([edge.stage_type for edge in edges if edge.stage_type]),
            evidence_relation_ids=relation_ids,
            evidence_refs=[ref for edge in edges for ref in edge.evidence_refs],
            board_support=board_support,
            metadata={"evidence_ids": evidence_ids},
        )


def _evidence_ids(edges: list[CrossBoardGraphEdge]) -> list[str]:
    ids: list[str] = []
    for edge in edges:
        ids.extend(edge.evidence_signal_ids)
        ids.extend(edge.evidence_claim_ids)
        if not edge.evidence_signal_ids and not edge.evidence_claim_ids:
            ids.append(edge.relation_id)
    return ids


def _duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _contradictory_count(edges: list[CrossBoardGraphEdge]) -> int:
    explicit = sum(
        1
        for edge in edges
        if edge.metadata.get("contradictory_evidence") is True
        or edge.metadata.get("contradicts") is True
        or edge.metadata.get("polarity") in {"negative", "contradictory"}
    )
    by_target: dict[str, set[str]] = {}
    for edge in edges:
        by_target.setdefault(edge.target_ref.object_id, set()).add(edge.relation_type.value)
    inferred = sum(1 for relation_types in by_target.values() if {"supports", "criticizes"} <= relation_types)
    return explicit + inferred


def _missing_stage_count(stage_types: list[str]) -> int:
    present = {stage for stage in stage_types if stage in ORDERED_STAGE_TYPES}
    return len(set(ORDERED_STAGE_TYPES) - present)


__all__ = ["CrossBoardEvidenceChainBuilder"]
