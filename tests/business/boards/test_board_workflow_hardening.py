from __future__ import annotations

import pytest

from business.boards._workflow import BoardWorkflowResult
from business.boards.ai_news.workflow import AINewsWorkflow
from business.boards.community_pulse.workflow import CommunityPulseWorkflow
from business.boards.paper_radar.workflow import PaperRadarWorkflow
from business.boards.project_radar.workflow import ProjectRadarWorkflow
from business.foundation import BoardRunResult, BoardType


@pytest.mark.parametrize(
    ("workflow_cls", "board_type"),
    [
        (AINewsWorkflow, BoardType.AI_NEWS),
        (ProjectRadarWorkflow, BoardType.PROJECT_RADAR),
        (PaperRadarWorkflow, BoardType.PAPER_RADAR),
        (CommunityPulseWorkflow, BoardType.COMMUNITY_PULSE),
    ],
)
def test_board_workflow_runs_with_trace_and_result(workflow_cls, board_type: BoardType) -> None:
    workflow_result = workflow_cls().run(_sample_raw_items())

    assert isinstance(workflow_result, BoardWorkflowResult)
    assert isinstance(workflow_result.result, BoardRunResult)
    assert workflow_result.trace.board_type == board_type
    assert workflow_result.trace.selected_signal_count >= 1
    assert workflow_result.trace.card_count >= 1
    assert workflow_result.trace.policy_profile_ids
    assert workflow_result.trace.quality_status in {"passed", "warning", "failed", "unchecked"}
    assert "raw_payload" not in workflow_result.result.to_dict()
    assert workflow_result.metadata["board_focus"]
    assert workflow_result.metadata["stages"] == [
        "resolve_context",
        "select_signals",
        "run_pipeline",
        "build_board_run_result",
        "apply_board_specific_policy",
        "collect_quality_feedback",
        "return_workflow_result",
    ]


def test_four_board_workflows_have_distinct_focus_metadata() -> None:
    results = [
        AINewsWorkflow().run(_sample_raw_items()),
        ProjectRadarWorkflow().run(_sample_raw_items()),
        PaperRadarWorkflow().run(_sample_raw_items()),
        CommunityPulseWorkflow().run(_sample_raw_items()),
    ]

    focuses = {result.metadata["board_focus"] for result in results}

    assert focuses == {
        "product_adoption_news",
        "project_implementation_radar",
        "research_method_radar",
        "community_discussion_pulse",
    }
    assert {result.trace.metadata["board_focus"] for result in results} == focuses


def _sample_raw_items() -> list[dict[str, object]]:
    return [
        _sample_raw_item("ai_news"),
        _sample_raw_item("github_project"),
        _sample_raw_item("paper"),
        _sample_raw_item("community_discussion"),
    ]


def _sample_raw_item(signal_type: str) -> dict[str, object]:
    source_type = {
        "ai_news": "rss",
        "github_project": "github",
        "paper": "arxiv",
        "community_discussion": "hackernews",
    }[signal_type]
    url = {
        "ai_news": "https://example.com/news/agent-memory",
        "github_project": "https://github.com/example/agent-memory",
        "paper": "https://arxiv.org/abs/2605.00001",
        "community_discussion": "https://news.ycombinator.com/item?id=1",
    }[signal_type]
    summary = {
        "ai_news": "OpenAI launches product adoption for agent memory and workflow APIs.",
        "github_project": "example/agent-memory implements agent memory with active commits and repo health.",
        "paper": "We propose a novel Agent Memory method with benchmark evaluation and ablation.",
        "community_discussion": "HN discusses agent memory reliability, latency, cost, and workflow tradeoffs.",
    }[signal_type]
    return {
        "source_item_id": f"{signal_type}-item",
        "source_id": f"{signal_type}-source",
        "source_name": "OpenAI Blog" if signal_type == "ai_news" else "Source",
        "source_type": source_type,
        "title": "Agent Memory update",
        "summary": summary,
        "content": summary,
        "url": url,
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai", "agent memory"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": "high", "source_authority_score": 0.9},
    }
