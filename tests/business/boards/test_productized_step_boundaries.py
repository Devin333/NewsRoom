from __future__ import annotations

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._productized_steps import ProductizedBoardSteps, build_productized_board_workflow
from business.boards.ai_news.board_service import AINewsBoardService
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillRuntime


def test_productized_steps_keep_only_workflow_boundary_state() -> None:
    steps = ProductizedBoardSteps(
        board_type=BoardType.AI_NEWS,
        board_service=AINewsBoardService(),
        skill_runtime=BusinessSkillRuntime(),
        feedback_service=BoardFeedbackService(),
        improvement_service=BoardImprovementService(),
    )

    assert set(steps.__dict__) == {"board_type", "usecases"}


def test_productized_workflow_declares_only_step_read_keys() -> None:
    workflow = build_productized_board_workflow(BoardType.AI_NEWS)
    read_keys_by_step = {step.step_id: step.read_keys for step in workflow.steps}

    assert read_keys_by_step["build_subscription_payload"] == [
        "request",
        "board_run_result",
        "board_output",
        "quality_summary",
    ]
    assert read_keys_by_step["build_feedback_events"] == ["board_run_result"]
