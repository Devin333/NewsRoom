from __future__ import annotations

from interfaces.services.business_acceptance_service import BusinessAcceptanceService


def test_business_acceptance_service_runs_board_acceptance_offline(tmp_path) -> None:
    result = BusinessAcceptanceService().run_board_acceptance(
        "ai_news",
        artifact_root=tmp_path,
        run_id="service-board-acceptance",
    )

    assert result.status == "passed"
    assert result.summary["board_type"] == "ai_news"
    assert any(check.check_id == "skills.trace" for check in result.checks)


def test_business_acceptance_service_runs_eval_acceptance_offline(tmp_path) -> None:
    result = BusinessAcceptanceService().run_eval_acceptance(
        artifact_root=tmp_path,
        run_id="service-eval-acceptance",
    )

    assert result.status == "passed"
    assert result.summary["area"] == "eval"
