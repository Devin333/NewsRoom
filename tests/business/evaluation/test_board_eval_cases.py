from __future__ import annotations

from collections import Counter

from business.evaluation.fixtures import board_eval_cases


def test_board_eval_cases_cover_four_boards_and_five_scenarios_each() -> None:
    cases = board_eval_cases()
    counts = Counter(case.board_type for case in cases)

    assert len(cases) == 20
    assert counts == {
        "ai_news": 5,
        "project_radar": 5,
        "paper_radar": 5,
        "community_pulse": 5,
    }
    assert all(case.expected_subscription_tags for case in cases)
