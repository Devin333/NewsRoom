from __future__ import annotations

from interfaces.services.board_service import BoardApplicationService, BoardWorkflowApplicationService


def test_final_business_run_contains_all_final_closure_surfaces() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(_sample_raw_items())

    assert len(result.board_workflow_results) == 4
    assert result.cross_board_graph.nodes
    assert result.cross_board_paths
    assert result.cross_board_insights
    assert result.quality_summary.checks
    assert result.feedback_events
    assert result.learning_signals
    assert result.policy_candidates
    assert result.regression_guard_results
    assert result.artifacts
    assert result.metadata["board_count"] == 4
    assert "raw_payload" not in result.to_dict()


def test_existing_board_application_service_methods_remain_compatible() -> None:
    service = BoardApplicationService()

    output = service.build_board_output("ai_news", _sample_raw_items())
    cross_board = service.build_cross_board_output(_sample_raw_items())

    assert output.cards
    assert cross_board.output.cards
    assert cross_board.board_outputs
    assert "raw_payload" not in output.to_dict()
    assert "raw_payload" not in cross_board.to_dict()


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
