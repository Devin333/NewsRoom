from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.boards.paper_radar.presenter import present_paper_cards
from business.boards.paper_radar.ranking_rules import PAPER_RADAR_PROFILE, paper_radar_features
from business.boards.services import BoardPolicyApplicationProfile, BoardPolicyApplicationService
from business.foundation import BoardType


class PaperRadarBoardService(BoardServiceBase):
    board_type = BoardType.PAPER_RADAR
    policy_application_service = BoardPolicyApplicationService(
        BoardPolicyApplicationProfile(
            scoring_profile=PAPER_RADAR_PROFILE,
            policy_factory=paper_radar_policy_profile,
            feature_builder=paper_radar_features,
            card_presenter=present_paper_cards,
        )
    )

    def _postprocess_board_output(self, output, **kwargs):
        return self.policy_application_service.present_output(output)

    def apply_board_specific_policy(self, result):
        return self.policy_application_service.apply_to_run_result(result)
