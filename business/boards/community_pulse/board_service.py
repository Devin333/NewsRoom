from __future__ import annotations

from business.boards._intelligence import enhance_board_run_result
from business.boards._service import BoardServiceBase
from business.boards.community_pulse.policies import community_pulse_policy_profile
from business.boards.community_pulse.presenter import present_community_cards
from business.boards.community_pulse.ranking_rules import COMMUNITY_PULSE_PROFILE, community_pulse_features
from business.foundation import BoardType


class CommunityPulseBoardService(BoardServiceBase):
    board_type = BoardType.COMMUNITY_PULSE

    def _postprocess_board_output(self, output, **kwargs):
        return output.model_copy(update={"cards": present_community_cards(list(output.cards))})

    def build_board_run_result(self, signals, *, context=None):
        result = super().build_board_run_result(signals, context=context)
        return enhance_board_run_result(
            result,
            profile=COMMUNITY_PULSE_PROFILE,
            policy=community_pulse_policy_profile(),
            feature_builder=community_pulse_features,
        )
