from __future__ import annotations

import pytest

from business.foundation import BoardType, SignalType
from interfaces.services.board_service import BoardApplicationService


@pytest.mark.parametrize(
    ("board_type", "sample_type", "expected_signal_type"),
    [
        (BoardType.AI_NEWS, "ai_news", SignalType.AI_NEWS),
        (BoardType.PROJECT_RADAR, "github_project", SignalType.GITHUB_PROJECT),
        (BoardType.PAPER_RADAR, "paper", SignalType.PAPER),
        (BoardType.COMMUNITY_PULSE, "community_discussion", SignalType.COMMUNITY_DISCUSSION),
    ],
)
def test_frontend_boards_build_cards_through_output_dtos(
    board_type: BoardType,
    sample_type: str,
    expected_signal_type: SignalType,
) -> None:
    service = BoardApplicationService()

    output = service.build_board_output(board_type, [_sample_raw_item(sample_type)])

    assert output.board_type == board_type
    assert output.stats.signal_count == 1
    assert output.cards
    card = output.cards[0]
    assert card.board_type == board_type
    assert card.score.factors
    assert card.confidence.factors
    assert card.badges
    assert card.metrics
    assert card.metadata["signal_id"]
    assert "raw_payload" not in card.to_dict()
    assert output.metadata["selection"]["signal_types"] == [expected_signal_type.value]


def test_cross_board_collects_all_four_signal_types() -> None:
    service = BoardApplicationService()

    result = service.build_cross_board_output(
        [
            _sample_raw_item("ai_news"),
            _sample_raw_item("github_project"),
            _sample_raw_item("paper"),
            _sample_raw_item("community_discussion"),
        ]
    )

    assert result.output.board_type == BoardType.CROSS_BOARD
    assert result.output.stats.signal_count == 4
    assert result.output.metadata["selection"]["signal_types"] == [
        SignalType.AI_NEWS.value,
        SignalType.GITHUB_PROJECT.value,
        SignalType.PAPER.value,
        SignalType.COMMUNITY_DISCUSSION.value,
    ]
    assert set(result.board_outputs) == {
        BoardType.AI_NEWS.value,
        BoardType.PROJECT_RADAR.value,
        BoardType.PAPER_RADAR.value,
        BoardType.COMMUNITY_PULSE.value,
    }


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
        "ai_news": "OpenAI adopts agent memory in an AI agent product update.",
        "github_project": "example/agent-memory implements agent memory for workflow orchestration.",
        "paper": "We propose Agent Memory for long-term memory in AI agents.",
        "community_discussion": "HN discusses agent memory reliability and workflow tradeoffs.",
    }[signal_type]
    return {
        "source_item_id": f"{signal_type}-item",
        "source_id": f"{signal_type}-source",
        "source_name": "Source",
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
