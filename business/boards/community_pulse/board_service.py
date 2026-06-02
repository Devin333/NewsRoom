from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.community_pulse.policies import community_pulse_policy_profile
from business.boards.community_pulse.presenter import present_community_cards
from business.boards.community_pulse.ranking_rules import COMMUNITY_PULSE_PROFILE, community_pulse_features
from business.boards.services import BoardPolicyApplicationProfile, BoardPolicyApplicationService
from business.foundation import BoardType


class CommunityPulseBoardService(BoardServiceBase):
    board_type = BoardType.COMMUNITY_PULSE
    policy_application_service = BoardPolicyApplicationService(
        BoardPolicyApplicationProfile(
            scoring_profile=COMMUNITY_PULSE_PROFILE,
            policy_factory=community_pulse_policy_profile,
            feature_builder=community_pulse_features,
            card_presenter=present_community_cards,
        )
    )

    def _postprocess_board_output(self, output, **kwargs):
        return self.policy_application_service.present_output(output)

    def apply_board_specific_policy(self, result):
        return self.policy_application_service.apply_to_run_result(result)
