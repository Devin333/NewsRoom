from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import ProductizedImprovementWorkflowService
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
    assert result["applied_overrides"] == []
    assert result["improvement_measurement"]["card_count_delta"] == 1
    assert result["self_improvement_report"]["next_actions"] == ["continue monitoring"]


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
