from __future__ import annotations

from business.boards._workflow import BoardWorkflowBase
from business.boards._productized_steps import build_productized_board_workflow
from business.boards.ai_news.board_service import AINewsBoardService
from business.boards.ai_news.ranking_rules import AI_NEWS_PROFILE
from business.foundation import BoardType


class AINewsWorkflow(BoardWorkflowBase[AINewsBoardService]):
    board_type = BoardType.AI_NEWS
    service_class = AINewsBoardService
    board_focus = AI_NEWS_PROFILE.focus
    workflow_stages = (
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    )


def build_ai_news_workflow():
    return build_productized_board_workflow(BoardType.AI_NEWS)


__all__ = ["AINewsWorkflow", "build_ai_news_workflow"]
