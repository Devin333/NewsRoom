from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.project_radar.policies import project_radar_policy_profile
from business.boards.project_radar.presenter import present_project_cards
from business.boards.project_radar.ranking_rules import PROJECT_RADAR_PROFILE, project_radar_features
from business.boards.services import BoardPolicyApplicationProfile, BoardPolicyApplicationService
from business.foundation import BoardType


class ProjectRadarBoardService(BoardServiceBase):
    board_type = BoardType.PROJECT_RADAR
    policy_application_service = BoardPolicyApplicationService(
        BoardPolicyApplicationProfile(
            scoring_profile=PROJECT_RADAR_PROFILE,
            policy_factory=project_radar_policy_profile,
            feature_builder=project_radar_features,
            card_presenter=present_project_cards,
        )
    )

    def _postprocess_board_output(self, output, **kwargs):
        return self.policy_application_service.present_output(output)

    def apply_board_specific_policy(self, result):
        return self.policy_application_service.apply_to_run_result(result)
