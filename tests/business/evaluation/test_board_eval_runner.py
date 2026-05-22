from __future__ import annotations

from business.evaluation import BoardEvalRunner
from business.evaluation.fixtures import board_eval_cases


def test_board_eval_runner_runs_case_offline(tmp_path) -> None:
    case = next(case for case in board_eval_cases() if case.case_id == "ai_news-happy")

    result = BoardEvalRunner(artifact_root=tmp_path).run_case(case)

    assert result.passed
    assert result.metrics["card_count"] >= 1
    assert result.metrics["unhandled_errors"] == 0


def test_board_eval_runner_runs_suite(tmp_path) -> None:
    report = BoardEvalRunner(artifact_root=tmp_path).run_suite(board_eval_cases()[:4])

    assert report.case_count == 4
    assert report.score > 0
    assert all("unhandled_errors" in result.metrics for result in report.results)
