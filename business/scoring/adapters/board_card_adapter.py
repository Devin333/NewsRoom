from __future__ import annotations

from typing import TYPE_CHECKING, Any

from business.boards._intelligence import (
    apply_scoring_result_to_card,
    feature_vector_from_board_card,
    scoring_target_from_board_card,
)
from business.foundation import BoardCard, BusinessPolicyProfile
from framework.scoring import FeatureVector, ScoringResult, ScoringTarget

if TYPE_CHECKING:
    from business.boards._intelligence import BoardScoringProfile


def board_card_scoring_target(card: BoardCard) -> ScoringTarget:
    return scoring_target_from_board_card(card)


def board_card_feature_vector(
    card: BoardCard,
    *,
    features: dict[str, float],
    metadata: dict[str, Any] | None = None,
) -> FeatureVector:
    vector = feature_vector_from_board_card(card, features=features)
    if not metadata:
        return vector
    return FeatureVector(
        values=dict(vector.values),
        missing_features=list(vector.missing_features),
        evidence_refs=list(vector.evidence_refs),
        metadata={**vector.metadata, **metadata},
    )


def apply_scoring_result_to_board_card(
    card: BoardCard,
    result: ScoringResult,
    *,
    profile: "BoardScoringProfile",
    policy: BusinessPolicyProfile,
) -> BoardCard:
    return apply_scoring_result_to_card(card, result, profile=profile, policy=policy)
