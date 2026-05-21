from __future__ import annotations

from interfaces.services.board_service import BoardWorkflowApplicationService, FinalBusinessRunResult


def test_board_workflow_application_service_runs_board_and_cross_board_graph() -> None:
    service = BoardWorkflowApplicationService()

    board_response = service.run_board_workflow("ai_news", _sample_raw_items())
    graph_response = service.run_cross_board_graph_intelligence(_sample_raw_items())

    assert board_response.workflow_result.result.cards
    assert graph_response.result.graph.nodes
    assert graph_response.result.paths
    assert "raw_payload" not in board_response.to_dict()
    assert "raw_payload" not in graph_response.to_dict()


def test_board_workflow_application_service_builds_final_business_run() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(_sample_raw_items())

    assert isinstance(result, FinalBusinessRunResult)
    assert set(result.board_workflow_results) == {
        "ai_news",
        "project_radar",
        "paper_radar",
        "community_pulse",
    }
    assert result.cross_board_graph.nodes
    assert result.cross_board_paths
    assert result.cross_board_insights
    assert result.policy_snapshot_refs
    assert result.quality_summary.status in {"passed", "warning", "failed", "unchecked"}
    assert result.artifacts
    assert "raw_payload" not in result.to_dict()
    assert result.model_dump(mode="json", exclude_none=True)


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
