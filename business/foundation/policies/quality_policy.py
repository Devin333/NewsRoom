from __future__ import annotations

from business.foundation.policies.base_policy import BasePolicy
from business.foundation.taxonomy import BoardType


class QualityPolicy(BasePolicy):
    minimum_quality_score: float = 0.5
    minimum_evidence_relations: int = 1
    minimum_source_count: int = 1
    minimum_project_quality_score: float = 0.45
    minimum_paper_relevance_score: float = 0.5
    minimum_community_signal_noise_ratio: float = 0.4

    def minimum_for_board(self, board_type: BoardType) -> float:
        if board_type == BoardType.PROJECT_RADAR:
            return self.minimum_project_quality_score
        if board_type == BoardType.RESEARCH:
            return self.minimum_paper_relevance_score
        if board_type == BoardType.COMMUNITY_PULSE:
            return self.minimum_community_signal_noise_ratio
        return self.minimum_quality_score


__all__ = ["QualityPolicy"]
