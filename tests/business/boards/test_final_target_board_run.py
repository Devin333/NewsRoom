from __future__ import annotations

from business.foundation import BoardRunResult, BoardType
from interfaces.services.board_service import BoardApplicationService


def test_board_run_result_has_policy_quality_feedback_contract() -> None:
    service = BoardApplicationService()
    board_service = service._services[BoardType.AI_NEWS]

    result = board_service.build_board_run_result([_sample_raw_item()])

    assert isinstance(result, BoardRunResult)
    assert result.policy_snapshot is not None
    assert result.quality_summary is not None
    assert result.cards
    assert result.cards[0].ranking_reason
    assert result.cards[0].ranking_features
    assert result.cards[0].evidence_refs
    assert result.cards[0].provenance is not None
    assert result.cards[0].quality is not None


def test_required_board_modules_are_importable() -> None:
    import business.boards.ai_news.models
    import business.boards.ai_news.policies
    import business.boards.ai_news.presenter
    import business.boards.ai_news.ranking_rules
    import business.boards.ai_news.workflow
    import business.boards.community_pulse.discussion_quality_rules
    import business.boards.community_pulse.hot_topic_rules
    import business.boards.project_radar.project_quality_rules
    import business.boards.paper_radar.technology_mapping_rules


def _sample_raw_item() -> dict[str, object]:
    return {
        "source_item_id": "ai-news-item",
        "source_id": "openai-blog",
        "source_name": "OpenAI Blog",
        "source_type": "official_blog",
        "title": "Agent Memory update",
        "summary": "OpenAI adopts agent memory in an AI agent product update.",
        "content": "OpenAI adopts agent memory in an AI agent product update.",
        "url": "https://example.com/news/agent-memory",
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai", "agent memory"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": "high", "source_authority_score": 0.9},
    }
