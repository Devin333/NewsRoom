from __future__ import annotations

from business.foundation.policies.base_policy import BasePolicy
from business.foundation.taxonomy import BoardType


class FreshnessPolicy(BasePolicy):
    freshness_window_days: int = 7
    decay_half_life_days: float = 3.5
    minimum_freshness_score: float = 0.25

    def window_days_for_board(self, board_type: BoardType) -> int:
        if board_type == BoardType.AI_NEWS:
            return 3
        if board_type == BoardType.PROJECT_RADAR:
            return 14
        if board_type == BoardType.RESEARCH:
            return 30
        if board_type == BoardType.COMMUNITY_PULSE:
            return 7
        return self.freshness_window_days


__all__ = ["FreshnessPolicy"]
