from __future__ import annotations

from business.evaluation import BoardEvalReport, BoardEvalResult


def test_board_eval_report_summarizes_score_and_pass_state() -> None:
    report = BoardEvalReport(
        results=[
            BoardEvalResult("case-1", "ai_news", True, 1.0),
            BoardEvalResult("case-2", "ai_news", False, 0.5, failures=["x"]),
        ]
    )

    payload = report.to_dict()
    assert not report.passed
    assert report.score == 0.75
    assert payload["case_count"] == 2
