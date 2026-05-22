from __future__ import annotations

import pytest

from business.boards._productized_steps import PRODUCTIZED_BOARD_STEPS
from business.boards.ai_news.workflow import build_ai_news_workflow
from business.boards.community_pulse.workflow import build_community_pulse_workflow
from business.boards.paper_radar.workflow import build_paper_radar_workflow
from business.boards.project_radar.workflow import build_project_radar_workflow


@pytest.mark.parametrize(
    "builder",
    [
        build_ai_news_workflow,
        build_project_radar_workflow,
        build_paper_radar_workflow,
        build_community_pulse_workflow,
    ],
)
def test_productized_board_workflow_has_required_steps(builder) -> None:
    workflow = builder()

    assert [step.step_id for step in workflow.steps] == list(PRODUCTIZED_BOARD_STEPS)
    assert workflow.start_step_id == "prepare_signals"
    assert workflow.terminal_step_ids == ["publish_board_artifacts"]
    assert all(step.implementation.endswith(step.step_id) for step in workflow.steps)
