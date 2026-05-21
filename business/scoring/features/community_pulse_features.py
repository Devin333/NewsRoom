from __future__ import annotations

from business.boards.community_pulse.ranking_rules import community_pulse_features
from business.foundation import BoardCard
from business.scoring.adapters.board_card_adapter import board_card_feature_vector
from framework.scoring import FeatureVector


def community_pulse_feature_vector(card: BoardCard) -> FeatureVector:
    return board_card_feature_vector(card, features=community_pulse_features(card), metadata={"feature_builder": "community_pulse"})
