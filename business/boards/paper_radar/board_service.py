from __future__ import annotations

from business.boards._intelligence import enhance_board_run_result
from business.boards._service import BoardServiceBase
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.boards.paper_radar.presenter import present_paper_cards
from business.boards.paper_radar.ranking_rules import PAPER_RADAR_PROFILE, paper_radar_features
from business.foundation import BoardType


class PaperRadarBoardService(BoardServiceBase):
    board_type = BoardType.PAPER_RADAR

    def _postprocess_board_output(self, output, **kwargs):
        return output.model_copy(update={"cards": present_paper_cards(list(output.cards))})

    def build_board_run_result(self, signals, *, context=None):
        result = super().build_board_run_result(signals, context=context)
        return enhance_board_run_result(
            result,
            profile=PAPER_RADAR_PROFILE,
            policy=paper_radar_policy_profile(),
            feature_builder=paper_radar_features,
        )
