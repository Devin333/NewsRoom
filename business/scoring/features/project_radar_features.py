from __future__ import annotations

from business.boards.project_radar.ranking_rules import project_radar_features
from business.foundation import BoardCard
from business.scoring.adapters.board_card_adapter import board_card_feature_vector
from framework.scoring import FeatureVector


def project_radar_feature_vector(card: BoardCard) -> FeatureVector:
    return board_card_feature_vector(card, features=project_radar_features(card), metadata={"feature_builder": "project_radar"})
