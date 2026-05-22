from __future__ import annotations

from business.boards._workflow import BoardWorkflowBase
from business.boards._productized_steps import build_productized_board_workflow
from business.boards.paper_radar.board_service import PaperRadarBoardService
from business.boards.paper_radar.ranking_rules import PAPER_RADAR_PROFILE
from business.foundation import BoardType


class PaperRadarWorkflow(BoardWorkflowBase[PaperRadarBoardService]):
    board_type = BoardType.PAPER_RADAR
    service_class = PaperRadarBoardService
    board_focus = PAPER_RADAR_PROFILE.focus
    workflow_stages = (
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    )


def build_paper_radar_workflow():
    return build_productized_board_workflow(BoardType.PAPER_RADAR)


__all__ = ["PaperRadarWorkflow", "build_paper_radar_workflow"]
