from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation.primitives import PrimitiveModel
from business.foundation.taxonomy import BoardType


class BasePolicy(PrimitiveModel):
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfidencePolicy(BasePolicy):
    minimum_display_confidence: float = 0.5
    minimum_relation_confidence: float = 0.5
    minimum_insight_confidence: float = 0.55
    minimum_output_confidence: float = 0.5

    def display_level(self, value: float) -> str:
        confidence = float(value)
        if confidence < 0.5:
            return "hidden"
        if confidence < 0.7:
            return "weak_related"
        if confidence < 0.9:
            return "related"
        return "strong_related"

    def can_display(self, value: float) -> bool:
        return float(value) >= self.minimum_display_confidence


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
        if board_type == BoardType.PAPER_RADAR:
            return self.minimum_paper_relevance_score
        if board_type == BoardType.COMMUNITY_PULSE:
            return self.minimum_community_signal_noise_ratio
        return self.minimum_quality_score


class FreshnessPolicy(BasePolicy):
    freshness_window_days: int = 7
    decay_half_life_days: float = 3.5
    minimum_freshness_score: float = 0.25

    def window_days_for_board(self, board_type: BoardType) -> int:
        if board_type == BoardType.AI_NEWS:
            return 3
        if board_type == BoardType.PROJECT_RADAR:
            return 14
        if board_type == BoardType.PAPER_RADAR:
            return 30
        if board_type == BoardType.COMMUNITY_PULSE:
            return 7
        return self.freshness_window_days
