from __future__ import annotations

from business.boards._workflow import BoardWorkflowBase
from business.boards._productized_steps import build_productized_board_workflow
from business.boards.community_pulse.board_service import CommunityPulseBoardService
from business.boards.community_pulse.ranking_rules import COMMUNITY_PULSE_PROFILE
from business.foundation import BoardType


class CommunityPulseWorkflow(BoardWorkflowBase[CommunityPulseBoardService]):
    board_type = BoardType.COMMUNITY_PULSE
    service_class = CommunityPulseBoardService
    board_focus = COMMUNITY_PULSE_PROFILE.focus
    workflow_stages = (
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    )


def build_community_pulse_workflow():
    return build_productized_board_workflow(BoardType.COMMUNITY_PULSE)


__all__ = ["CommunityPulseWorkflow", "build_community_pulse_workflow"]
