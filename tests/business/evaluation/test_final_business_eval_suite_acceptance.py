from __future__ import annotations

from collections import Counter

from business.evaluation import BoardEvalRunner, board_eval_cases


def test_final_business_eval_suite_acceptance(tmp_path) -> None:
    cases = board_eval_cases()
    counts = Counter(case.board_type for case in cases)

    assert len(cases) >= 20
    for board_type in ("ai_news", "project_radar", "paper_radar", "community_pulse"):
        assert counts[board_type] >= 5

    report = BoardEvalRunner(artifact_root=tmp_path).run_suite(cases)

    assert report.case_count == len(cases)
    assert hasattr(report, "pass_rate")
    assert 0.0 <= report.pass_rate <= 1.0
    assert report.to_dict()["pass_rate"] == report.pass_rate

    for result in report.results:
        assert result.metrics
        assert result.metrics.get("unhandled_errors") == 0
        if not result.passed:
            assert result.failures
