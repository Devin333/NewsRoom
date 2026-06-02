from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.ai_news.policies import ai_news_policy_profile
from business.boards.ai_news.presenter import present_ai_news_cards
from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE, ai_news_features
from business.boards.services import BoardPolicyApplicationProfile, BoardPolicyApplicationService
from business.foundation import BoardType


class AINewsBoardService(BoardServiceBase):
    board_type = BoardType.AI_NEWS
    policy_application_service = BoardPolicyApplicationService(
        BoardPolicyApplicationProfile(
            scoring_profile=AI_NEWS_PROFILE,
            policy_factory=ai_news_policy_profile,
            feature_builder=ai_news_features,
            card_presenter=present_ai_news_cards,
        )
    )

    def _postprocess_board_output(self, output, **kwargs):
        return self.policy_application_service.present_output(output)

    def apply_board_specific_policy(self, result):
        return self.policy_application_service.apply_to_run_result(result)
