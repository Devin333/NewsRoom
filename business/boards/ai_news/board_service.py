from __future__ import annotations

from business.boards._intelligence import enhance_board_run_result
from business.boards._service import BoardServiceBase
from business.boards.ai_news.policies import ai_news_policy_profile
from business.boards.ai_news.presenter import present_ai_news_cards
from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE, ai_news_features
from business.foundation import BoardType


class AINewsBoardService(BoardServiceBase):
    board_type = BoardType.AI_NEWS

    def _postprocess_board_output(self, output, **kwargs):
        return output.model_copy(update={"cards": present_ai_news_cards(list(output.cards))})

    def build_board_run_result(self, signals, *, context=None):
        result = super().build_board_run_result(signals, context=context)
        return enhance_board_run_result(
            result,
            profile=AI_NEWS_PROFILE,
            policy=ai_news_policy_profile(),
            feature_builder=ai_news_features,
        )
