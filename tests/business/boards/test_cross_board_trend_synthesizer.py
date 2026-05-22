from __future__ import annotations

from business.boards.cross_board.trend_synthesizer import TrendSynthesizer


def test_cross_board_trend_synthesizer_creates_board_and_cross_cutting_trends() -> None:
    payloads = {
        "ai_news": {"cards": [{"title": "OpenAI Agent Memory", "entities": [{"name": "OpenAI"}]}], "subscription_payload": {"targets": [{"entities": ["OpenAI"]}]}},
        "paper_radar": {"cards": [{"title": "OpenAI Agent Memory", "entities": [{"name": "OpenAI"}]}], "subscription_payload": {"targets": [{"entities": ["OpenAI"]}]}},
    }

    trends = TrendSynthesizer().synthesize(payloads)

    assert any(trend["trend_type"] == "cross_cutting" for trend in trends)
    assert any(trend["trend_type"] == "product" for trend in trends)
