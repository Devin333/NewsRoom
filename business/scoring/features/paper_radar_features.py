from __future__ import annotations

from business.boards.paper_radar.ranking_rules import paper_radar_features
from business.foundation import BoardCard
from business.scoring.adapters.board_card_adapter import board_card_feature_vector
from framework.scoring import FeatureVector


def paper_radar_feature_vector(card: BoardCard) -> FeatureVector:
    return board_card_feature_vector(card, features=paper_radar_features(card), metadata={"feature_builder": "paper_radar"})
