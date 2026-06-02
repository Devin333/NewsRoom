from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import ProductizedImprovementWorkflowService, ProductizedRunState
from business.foundation import BoardType


class StubBoardRunResult:
    metadata: dict[str, object] = {}


def test_productized_improvement_workflow_service_builds_outputs_from_request() -> None:
    service = ProductizedImprovementWorkflowService(
        improvement_service=BoardImprovementService(),
        board_type=BoardType.AI_NEWS,
    )

    result = service.build_outputs(
        request={"run_id": "improvement-run"},
        board_run_result=StubBoardRunResult(),
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        feedback_events=[],
        learning_signals=[],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
    )

    assert result["improvement_recommendations"] is not None
    assert result["improvement_proposals"] is not None
    assert result["applied_policy_experiments"] == []
    assert result["skipped_policy_experiments"] == []
    assert result["applied_overrides"] == []
    assert result["improvement_measurement"]["card_count_delta"] == 1
    assert result["self_improvement_report"]["applied_policy_experiments"] == []
    assert result["self_improvement_report"]["next_actions"] == ["continue monitoring"]


def test_productized_improvement_measurement_reads_formal_productized_run_state() -> None:
    service = ProductizedImprovementWorkflowService(
        improvement_service=BoardImprovementService(),
        board_type=BoardType.AI_NEWS,
    )
    productized_run = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="improvement-run",
        deduplication_result={
            "event_groups": [
                {"item_ids": ["signal-1", "signal-2"]},
                {"item_ids": ["signal-3"]},
            ]
        },
    )

    result = service.build_outputs(
        request={
            "run_id": "improvement-run",
            "previous_measurement_baseline": {"duplicate_rate": 0.0},
        },
        board_run_result=StubBoardRunResult(),
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        feedback_events=[],
        learning_signals=[],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
        productized_run=productized_run,
    )

    assert result["improvement_measurement"]["duplicate_rate_delta"] == 0.5


def test_productized_improvement_workflow_service_requires_board_type_for_outputs() -> None:
    service = ProductizedImprovementWorkflowService(improvement_service=BoardImprovementService())

    try:
        service.build_outputs(
            request={"run_id": "missing-board-type"},
            board_run_result=StubBoardRunResult(),
            quality_summary={},
            cards=[],
            feedback_events=[],
            learning_signals=[],
            subscription_payload={},
        )
    except ValueError as exc:
        assert "board_type" in str(exc)
    else:
        raise AssertionError("expected board_type validation error")
