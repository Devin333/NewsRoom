from __future__ import annotations

from business.boards.cross_board.graph_models import CrossBoardInsightCandidate, CrossBoardPath
from business.foundation import build_stable_id


class CrossBoardInsightRanker:
    def rank(self, paths: list[CrossBoardPath]) -> list[CrossBoardInsightCandidate]:
        candidates = [
            self._candidate(path)
            for path in paths
            if path.evidence_chain is not None and path.guard_result is not None and not _is_runtime_blocked(path)
        ]
        return sorted(candidates, key=lambda candidate: (candidate.score, candidate.confidence), reverse=True)

    def _candidate(self, path: CrossBoardPath) -> CrossBoardInsightCandidate:
        chain = path.evidence_chain
        guard = path.guard_result
        assert chain is not None
        assert guard is not None
        tech_name = path.technology_ref.label or path.technology_ref.object_id
        score = _candidate_score(path)
        return CrossBoardInsightCandidate(
            candidate_id=build_stable_id("cross_insight_candidate", path.path_id, score),
            path=path,
            title=f"{tech_name} cross-board journey",
            summary=f"{tech_name} has {len(path.board_sequence)} supported stage(s) across {chain.board_support_count} board(s).",
            evidence_chain=chain,
            guard_result=guard,
            score=score,
            confidence=path.confidence,
            metadata={
                "board_sequence": path.board_sequence,
                "blocking_reasons": path.blocking_reasons,
                "warnings": guard.warnings,
                "scoring_result": path.metadata.get("scoring_result"),
                "scoring_recipe_id": path.metadata.get("scoring_recipe_id"),
                "scoring_blocked": path.metadata.get("scoring_blocked", False),
            },
        )


def _candidate_score(path: CrossBoardPath) -> float:
    if path.evidence_chain is None:
        return path.path_score
    duplicate_penalty = min(0.2, path.evidence_chain.duplicate_evidence_count * 0.05)
    warning_penalty = 0.05 if path.guard_result and path.guard_result.warnings else 0.0
    block_penalty = 0.4 if path.blocking_reasons else 0.0
    return round(max(0.0, min(1.0, path.path_score - duplicate_penalty - warning_penalty - block_penalty)), 4)


def _is_runtime_blocked(path: CrossBoardPath) -> bool:
    return bool(path.metadata.get("scoring_blocked")) or bool(path.blocking_reasons)


__all__ = ["CrossBoardInsightRanker"]
