from __future__ import annotations

import pytest

from business.boards._runner import runner_for_board_type
from business.evaluation.fixtures import sample_signal


EXPECTED_TAGS = {
    "ai_news": {"ai_news", "product_update", "industry"},
    "project_radar": {"github", "project", "framework", "release"},
    "paper_radar": {"paper", "arxiv", "research", "benchmark"},
    "community_pulse": {"community", "discussion", "sentiment", "developer"},
}


@pytest.mark.parametrize("board_type", sorted(EXPECTED_TAGS))
def test_each_board_generates_subscription_payload(board_type: str, tmp_path) -> None:
    result = runner_for_board_type(board_type, artifact_root=tmp_path).run(
        signals=[
            sample_signal("ai_news"),
            sample_signal("github_project"),
            sample_signal("paper"),
            sample_signal("community_discussion"),
        ],
        topic="Agent Memory",
        run_id=f"subscription-{board_type}",
    )

    payload = result.output["subscription_payload"]
    target = payload["targets"][0]
    assert EXPECTED_TAGS[board_type].issubset(set(target["tags"]))
    assert target["source_types"]
    assert target["entities"]
    assert payload["cards"]
    assert payload["delivery_plan"]["channels"]
