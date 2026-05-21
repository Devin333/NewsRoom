from __future__ import annotations

import pytest

from business.boards.ai_news.workflow import AINewsWorkflow
from business.boards.community_pulse.workflow import CommunityPulseWorkflow
from business.boards.paper_radar.workflow import PaperRadarWorkflow
from business.boards.project_radar.workflow import ProjectRadarWorkflow
from business.foundation import BoardRunResult, BoardType


@pytest.mark.parametrize(
    ("workflow_cls", "board_type", "focus"),
    [
        (AINewsWorkflow, BoardType.AI_NEWS, "product_adoption_news"),
        (ProjectRadarWorkflow, BoardType.PROJECT_RADAR, "project_implementation_radar"),
        (PaperRadarWorkflow, BoardType.PAPER_RADAR, "research_method_radar"),
        (CommunityPulseWorkflow, BoardType.COMMUNITY_PULSE, "community_discussion_pulse"),
    ],
)
def test_board_workflow_final_trace_and_closure_fields(workflow_cls, board_type: BoardType, focus: str) -> None:
    result = workflow_cls().run(_sample_raw_items())

    assert isinstance(result.result, BoardRunResult)
    assert result.trace.board_type == board_type
    assert result.trace.card_count >= 1
    assert result.trace.artifact_count >= 1
    assert result.trace.evidence_count >= 1
    assert result.trace.policy_profile_ids
    assert result.trace.guard_status in {"pass", "warning", "block", "unchecked"}
    assert result.metadata["board_focus"] == focus
    assert result.result.artifact_refs
    assert result.result.evidence_refs
    assert result.result.trace_ref is not None
    assert result.result.manifest_ref is not None
    assert "raw_payload" not in result.to_dict()


def test_four_workflows_keep_distinct_focus_and_ranking_features() -> None:
    results = [
        AINewsWorkflow().run(_sample_raw_items()),
        ProjectRadarWorkflow().run(_sample_raw_items()),
        PaperRadarWorkflow().run(_sample_raw_items()),
        CommunityPulseWorkflow().run(_sample_raw_items()),
    ]

    focuses = {result.metadata["board_focus"] for result in results}
    feature_focuses = {result.result.cards[0].ranking_features["board_focus"] for result in results}

    assert focuses == {
        "product_adoption_news",
        "project_implementation_radar",
        "research_method_radar",
        "community_discussion_pulse",
    }
    assert feature_focuses == focuses


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
        "url": f"https://example.com/{signal_type}",
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai", "agent memory"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": "high", "source_authority_score": 0.9},
    }
