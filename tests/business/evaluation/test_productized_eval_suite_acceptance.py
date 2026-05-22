from __future__ import annotations

from collections import Counter

from business.evaluation import BoardEvalRunner, board_eval_cases


def test_productized_eval_suite_acceptance(tmp_path) -> None:
    cases = board_eval_cases()
    counts = Counter(case.board_type for case in cases)

    assert len(cases) >= 20
    assert counts == {
        "ai_news": 5,
        "project_radar": 5,
        "paper_radar": 5,
        "community_pulse": 5,
    }

    report = BoardEvalRunner(artifact_root=tmp_path).run_suite(cases)

    assert report.case_count == len(cases)
    assert report.pass_rate == 1.0
    assert report.passed is True
    for result in report.results:
        assert result.metrics
        assert result.metrics["unhandled_errors"] == 0
        if not result.passed:
            assert result.failures
