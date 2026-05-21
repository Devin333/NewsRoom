from __future__ import annotations

from business.boards.cross_board.graph_models import CrossBoardPath
from business.boards.cross_board.regression_guard import ORDERED_STAGE_TYPES


def cross_board_path_features(path: CrossBoardPath) -> dict[str, float]:
    stage_total = max(1, len(ORDERED_STAGE_TYPES))
    stage_completeness = (stage_total - len(path.missing_stage_types)) / stage_total
    board_support = min(1.0, len(set(path.board_sequence)) / stage_total)
    evidence_count = len(path.evidence_relation_ids)
    evidence_diversity = min(1.0, max(0.0, (evidence_count - path.duplicate_evidence_count) / stage_total))
    contradiction_penalty = 0.25 if path.contradictory_evidence_count else 0.0
    chain = path.evidence_chain
    chain_confidence = chain.average_relation_confidence if chain is not None else path.confidence
    return {
        "stage_completeness": round(max(0.0, min(1.0, stage_completeness)), 4),
        "board_support": round(max(0.0, min(1.0, board_support)), 4),
        "evidence_chain_confidence": round(max(0.0, min(1.0, chain_confidence)), 4),
        "evidence_diversity": round(max(0.0, min(1.0, evidence_diversity)), 4),
        "contradiction_penalty": round(max(0.0, min(1.0, contradiction_penalty)), 4),
        "duplicate_count": float(path.duplicate_evidence_count),
        "missing_stage_count": float(len(path.missing_stage_types)),
    }
