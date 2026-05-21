from business.boards._final_target import present_cards
from business.boards.ai_news.policies import ai_news_policy_profile
from business.foundation import BoardCard


def present_ai_news_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return present_cards(cards, ai_news_policy_profile())
