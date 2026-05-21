from __future__ import annotations

from business.boards._intelligence import enhance_board_run_result
from business.boards._service import BoardServiceBase
from business.boards.project_radar.policies import project_radar_policy_profile
from business.boards.project_radar.presenter import present_project_cards
from business.boards.project_radar.ranking_rules import PROJECT_RADAR_PROFILE, project_radar_features
from business.foundation import BoardType


class ProjectRadarBoardService(BoardServiceBase):
    board_type = BoardType.PROJECT_RADAR

    def _postprocess_board_output(self, output, **kwargs):
        return output.model_copy(update={"cards": present_project_cards(list(output.cards))})

    def build_board_run_result(self, signals, *, context=None):
        result = super().build_board_run_result(signals, context=context)
        return enhance_board_run_result(
            result,
            profile=PROJECT_RADAR_PROFILE,
            policy=project_radar_policy_profile(),
            feature_builder=project_radar_features,
        )
