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


def test_business_acceptance_service_runs_final_business_acceptance_offline(tmp_path) -> None:
    result = BusinessAcceptanceService().run_final_business_acceptance(
        artifact_root=tmp_path,
        run_id="service-final-acceptance",
    )

    assert result.status == "passed"
    assert result.summary["area"] == "final-business"
    check_ids = {check.check_id for check in result.checks}
    assert {
        "final_business_run_surface",
        "no_raw_payload",
        "four_board_workflows",
        "artifacts_present",
        "serializable_model_dump",
    } <= check_ids


def test_business_acceptance_service_runs_eval_acceptance_offline(tmp_path) -> None:
    result = BusinessAcceptanceService().run_eval_acceptance(
        artifact_root=tmp_path,
        run_id="service-eval-acceptance",
    )

    assert result.status == "passed"
    assert result.summary["area"] == "eval"
