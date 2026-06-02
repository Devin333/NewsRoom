from __future__ import annotations

from business.boards.cross_board import CrossBoardGraphIntelligenceService, CrossBoardRunResultEnricher
from business.boards.cross_board.run_result_enricher import cross_board_learning_closure
from business.foundation import BoardType, BusinessFeedbackEvent
from business.foundation.feedback import RuntimeQualityClosure
from interfaces.services.board_service import BoardApplicationService


def test_four_boards_emit_distinct_ranking_features_and_reasons() -> None:
    service = BoardApplicationService()
    items = [
        _sample_raw_item("ai_news"),
        _sample_raw_item("github_project"),
        _sample_raw_item("paper"),
        _sample_raw_item("community_discussion"),
    ]

    results = {
        board_type: service._services[board_type].build_board_run_result(items)
        for board_type in (
            BoardType.AI_NEWS,
            BoardType.PROJECT_RADAR,
            BoardType.PAPER_RADAR,
            BoardType.COMMUNITY_PULSE,
        )
    }

    focuses = {result.cards[0].metadata["board_focus"] for result in results.values()}
    reasons = {result.cards[0].ranking_reason for result in results.values()}

    assert focuses == {
        "product_adoption_news",
        "project_implementation_radar",
        "research_method_radar",
        "community_discussion_pulse",
    }
    assert len(reasons) == 4
    for result in results.values():
        assert result.quality_summary is not None
        assert result.cards[0].ranking_features["policy_profile_id"]
        assert "raw_payload" not in result.to_dict()


def test_board_run_metadata_contains_processed_relations_for_cross_board_guards() -> None:
    service = BoardApplicationService()
    cross_board_service = service._services[BoardType.CROSS_BOARD]

    assert isinstance(cross_board_service.graph_intelligence_service, CrossBoardGraphIntelligenceService)
    assert isinstance(cross_board_service.run_result_enricher, CrossBoardRunResultEnricher)

    result = cross_board_service.build_board_run_result(
        [
            _sample_raw_item("paper"),
            _sample_raw_item("github_project"),
            _sample_raw_item("community_discussion"),
            _sample_raw_item("ai_news"),
        ]
    )

    assert result.metadata["processed_relations"]
    assert "cross_board_insights" in result.metadata
    assert "cross_board_learning_signals" in result.metadata
    assert "cross_board_policy_candidates" in result.metadata


def test_cross_board_learning_closure_uses_foundation_feedback_runtime_closure() -> None:
    feedback = [
        BusinessFeedbackEvent.create(
            target_object_type="cross_board_path",
            target_object_id="path-1",
            target_layer="cross_board_graph",
            board_type=BoardType.CROSS_BOARD.value,
            feedback_type="duplicate_evidence",
            severity="warning",
        )
    ]

    closure = cross_board_learning_closure(feedback)

    assert isinstance(closure, RuntimeQualityClosure)
    assert closure.feedback_events == feedback
    assert closure.learning_signals
    assert closure.policy_candidates
    assert closure.guard_results


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
