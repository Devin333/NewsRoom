from __future__ import annotations

from business.boards.cross_board.conflict_detector import ConflictDetector


def test_cross_board_conflict_detector_detects_quality_and_semantic_conflicts() -> None:
    payloads = {
        "ai_news": _payload("OpenAI", 0.95),
        "project_radar": _payload("OpenAI", 0.45),
        "paper_radar": _payload("MCP", 0.8),
        "community_pulse": _payload("MCP", 0.8),
    }

    conflicts = ConflictDetector().detect(payloads)

    assert any(conflict["conflict_type"] == "quality_judgment" for conflict in conflicts)
    assert any(conflict["conflict_type"] == "paper_vs_community" for conflict in conflicts)


def _payload(entity: str, score: float) -> dict:
    return {
        "cards": [{"entities": [{"name": entity}]}],
        "quality_summary": {"score": score},
        "subscription_payload": {"targets": [{"entities": [entity]}]},
    }
