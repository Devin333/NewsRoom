from __future__ import annotations

from business.foundation import BoardType
from business.layers.output import BoardOutput
from interfaces.services.board_service import BoardApplicationService


def test_board_application_service_lists_boards() -> None:
    service = BoardApplicationService()

    boards = service.list_boards()

    assert {board["board_type"] for board in boards} == {
        BoardType.AI_NEWS.value,
        BoardType.PROJECT_RADAR.value,
        BoardType.PAPER_RADAR.value,
        BoardType.COMMUNITY_PULSE.value,
        BoardType.CROSS_BOARD.value,
    }


def test_board_application_service_rejects_invalid_board_type() -> None:
    service = BoardApplicationService()

    try:
        service.build_board_output("not-a-board", [])
    except ValueError as exc:
        assert "unsupported board_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_board_services_build_output_from_signals() -> None:
    service = BoardApplicationService()
    output = service.build_board_output("ai_news", [_sample_raw_item("ai_news")])

    assert isinstance(output, BoardOutput)
    assert output.board_type == BoardType.AI_NEWS
    assert output.stats.signal_count == 1
    assert output.metadata["board_type"] == BoardType.AI_NEWS.value


def test_cross_board_output_contains_report_payload() -> None:
    service = BoardApplicationService()
    result = service.build_cross_board_output([
        _sample_raw_item("paper"),
        _sample_raw_item("github_project"),
        _sample_raw_item("community_discussion"),
        _sample_raw_item("ai_news"),
    ])

    assert result.output.board_type == BoardType.CROSS_BOARD
    assert "report" in result.output.metadata
    assert set(result.board_outputs) == {
        BoardType.AI_NEWS.value,
        BoardType.PROJECT_RADAR.value,
        BoardType.PAPER_RADAR.value,
        BoardType.COMMUNITY_PULSE.value,
    }


def test_run_output_attachment_adds_cross_board_output() -> None:
    service = BoardApplicationService()
    output = {"ranked_items": [_sample_ranked_item("ai_news")]}

    service.attach_run_board_outputs(output, topic="AI policy")

    assert "cross_board_output" in output
    assert "board_outputs" in output


def _sample_raw_item(signal_type: str) -> dict[str, object]:
    source_type = {
        "ai_news": "rss",
        "github_project": "github",
        "paper": "arxiv",
        "community_discussion": "hackernews",
    }[signal_type]
    return {
        "source_item_id": f"{signal_type}-item",
        "source_id": f"{signal_type}-source",
        "source_name": "Source",
        "source_type": source_type,
        "title": "Agent Memory update",
        "summary": "Signal summary",
        "content": "Signal content",
        "url": "https://example.com/item",
        "language": "en",
        "authors": ["Alice"],
        "tags": ["ai"],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {"source_reliability": "high", "source_authority_score": 0.9},
    }


def _sample_ranked_item(signal_type: str) -> dict[str, object]:
    raw = _sample_raw_item(signal_type)
    normalized = {
        "normalized_item_id": f"norm_{signal_type}",
        "source_item_id": raw["source_item_id"],
        "source_id": raw["source_id"],
        "title": raw["title"],
        "normalized_title": str(raw["title"]).casefold(),
        "url": raw["url"],
        "canonical_url": raw["url"],
        "canonical_url_hash": "hash",
        "title_hash": "hash",
        "content_hash": "hash",
        "source_reliability": "high",
        "fetched_at": raw["fetched_at"],
        "published_at": raw["published_at"],
        "summary": raw["summary"],
        "normalized_summary": str(raw["summary"]).casefold(),
        "language": "en",
        "metadata": dict(raw["metadata"]),
    }
    return {
        "ranked_item_id": f"rank_{signal_type}",
        "item": normalized,
        "relevance_score": 0.9,
        "recency_score": 0.8,
        "reliability_score": 0.9,
        "novelty_score": 0.8,
        "final_score": 0.85,
        "authority_score": 0.9,
        "duplicate_cluster_score": 0.5,
        "historical_importance_score": 0.5,
        "subscription_match_score": 0.5,
        "source_quality_score": 0.9,
        "rank_reason": "test",
        "metadata": {"lineage": {"source_id": raw["source_id"], "source_item_id": raw["source_item_id"], "normalized_item_id": f"norm_{signal_type}", "ranked_item_id": f"rank_{signal_type}"}},
    }
