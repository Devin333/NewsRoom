from __future__ import annotations

from business.boards.ai_news.ranking_rules import ai_news_features
from business.foundation import BoardCard
from business.scoring.adapters.board_card_adapter import board_card_feature_vector
from framework.scoring import FeatureVector


def ai_news_feature_vector(card: BoardCard) -> FeatureVector:
    return board_card_feature_vector(card, features=ai_news_features(card), metadata={"feature_builder": "ai_news"})
