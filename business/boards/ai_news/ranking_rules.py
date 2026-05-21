from business.boards._final_target import ranking_payload
from business.boards.ai_news.policies import ai_news_policy_profile
from business.foundation import BoardCard


def rank_ai_news_card(card: BoardCard):
    return ranking_payload(card, ai_news_policy_profile())
