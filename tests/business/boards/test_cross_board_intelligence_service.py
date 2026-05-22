from __future__ import annotations

from business.boards.cross_board.intelligence_service import CrossBoardIntelligenceService


def test_cross_board_intelligence_service_builds_product_surfaces() -> None:
    payloads = {
        "ai_news": _payload("ai_news"),
        "project_radar": _payload("project_radar"),
        "paper_radar": _payload("paper_radar"),
        "community_pulse": _payload("community_pulse"),
    }

    result = CrossBoardIntelligenceService().build(payloads, topic="Agent Memory")

    assert result["cross_board_summary"]
    assert result["shared_trends"]
    assert result["board_coverage"]["ai_news"]["card_count"] == 1
    assert result["subscription_payload"]["targets"]
    assert "improvement_report" in result


def _payload(board_type: str) -> dict:
    return {
        "cards": [{"card_id": board_type, "title": "Agent Memory", "entities": [{"name": "OpenAI"}], "evidence_refs": [{"source_id": "s"}]}],
        "quality_summary": {"score": 0.9},
        "subscription_payload": {
            "run_id": board_type,
            "board_type": board_type,
            "topic": "Agent Memory",
            "targets": [{"board_type": board_type, "topic": "Agent Memory", "tags": [board_type], "entities": ["OpenAI"], "source_types": ["web"], "priority": "normal"}],
            "cards": [],
            "summary": "summary",
            "quality_score": 0.9,
            "delivery_hints": {"subscription_ready": True},
        },
        "improvement_recommendations": [{"recommendation_id": f"rec-{board_type}", "severity": "info"}],
    }
