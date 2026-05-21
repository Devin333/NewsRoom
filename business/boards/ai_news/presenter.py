from business.boards._intelligence import enhance_board_cards
from business.boards.ai_news.policies import ai_news_policy_profile
from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE, ai_news_features
from business.foundation import BoardCard


def present_ai_news_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return enhance_board_cards(
        cards,
        profile=AI_NEWS_PROFILE,
        policy=ai_news_policy_profile(),
        feature_builder=ai_news_features,
    )
