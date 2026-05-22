from __future__ import annotations

from business.boards._workflow import BoardWorkflowBase
from business.boards._productized_steps import build_productized_board_workflow
from business.boards.project_radar.board_service import ProjectRadarBoardService
from business.boards.project_radar.ranking_rules import PROJECT_RADAR_PROFILE
from business.foundation import BoardType


class ProjectRadarWorkflow(BoardWorkflowBase[ProjectRadarBoardService]):
    board_type = BoardType.PROJECT_RADAR
    service_class = ProjectRadarBoardService
    board_focus = PROJECT_RADAR_PROFILE.focus
    workflow_stages = (
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    )


def build_project_radar_workflow():
    return build_productized_board_workflow(BoardType.PROJECT_RADAR)


__all__ = ["ProjectRadarWorkflow", "build_project_radar_workflow"]
