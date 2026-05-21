from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.graph_models import CrossBoardPath
from business.boards.cross_board.regression_guard import guard_cross_board_path
from business.scoring import (
    cross_board_path_feature_vector,
    cross_board_path_scoring_recipe,
    cross_board_path_scoring_target,
)
from framework.scoring import ScoringContext, ScoringRuntime


@dataclass
class CrossBoardPathScoringService:
    runtime: ScoringRuntime | None = None

    def __post_init__(self) -> None:
        if self.runtime is None:
            self.runtime = ScoringRuntime()

    def score_path(
        self,
        path: CrossBoardPath,
        *,
        context: ScoringContext | None = None,
    ) -> CrossBoardPath:
        recipe = cross_board_path_scoring_recipe()
        result = self.runtime.score_path(
            cross_board_path_scoring_target(path),
            features=cross_board_path_feature_vector(path),
            recipe=recipe,
            context=context,
        )
        runtime_blocking_reasons: list[str] = []
        for gate in result.gates:
            reason = gate.reason or gate.gate_id
            if gate.blocked and reason not in runtime_blocking_reasons:
                runtime_blocking_reasons.append(reason)
        metadata = {
            **dict(path.metadata),
            "scoring_result": result.to_dict(),
            "scoring_recipe_id": result.recipe_id,
            "scoring_trace_id": result.metadata.get("trace_id"),
            "scoring_blocked": result.blocked,
            "scoring_review_required": result.review_required,
        }
        scored = path.model_copy(
            update={
                "path_score": result.final_score,
                "confidence": result.score.confidence or path.confidence,
                "metadata": metadata,
            }
        )
        guard = guard_cross_board_path(scored)
        blocking_reasons = list(guard.blocking_reasons)
        for reason in runtime_blocking_reasons:
            if reason not in blocking_reasons:
                blocking_reasons.append(reason)
        return scored.model_copy(
            update={
                "quality_checks": guard.checks,
                "blocking_reasons": blocking_reasons,
                "guard_result": guard,
            }
        )


__all__ = ["CrossBoardPathScoringService"]
