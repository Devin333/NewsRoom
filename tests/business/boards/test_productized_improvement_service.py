from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import (
    ProductizedImprovementMeasurementInput,
    ProductizedImprovementMeasurementService,
    ProductizedImprovementWorkflowService,
    ProductizedRunState,
)
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
    assert result["policy_experiment_profiles"] == []
    assert result["policy_experiment_profile_ids"] == []
    assert result["policy_experiment_application_context"] == {
        "run_id": "improvement-run",
        "board_type": "ai_news",
        "applied_policy_experiments": [],
        "skipped_policy_experiments": [],
        "proposal_ids": [],
        "measurement_plan": {
            "compare_metrics": [
                "quality_score",
                "card_count",
                "evidence_coverage",
                "duplicate_rate",
                "empty_output",
                "subscription_match",
            ],
        },
        "applied_overrides": [],
        "skipped_overrides": [],
    }
    assert result["applied_policy_experiments"] == []
    assert result["skipped_policy_experiments"] == []
    assert result["applied_overrides"] == []
    assert result["improvement_measurement"]["card_count_delta"] == 1
    assert result["self_improvement_report"]["applied_policy_experiments"] == []
    assert result["self_improvement_report"]["next_actions"] == ["continue monitoring"]


def test_productized_improvement_workflow_exports_policy_experiment_profiles() -> None:
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
        learning_signals=[
            {
                "signal_id": "learning-1",
                "signal_type": "top_cards_have_evidence",
                "board_type": "ai_news",
                "target_layer": "board",
                "description": "Top cards need stronger evidence.",
                "frequency": 1,
                "severity_score": 0.8,
                "related_feedback_ids": ["feedback-1"],
            }
        ],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
    )

    assert result["policy_experiment_profiles"]
    assert result["policy_experiment_profile_ids"] == [
        result["policy_experiment_profiles"][0]["profile_id"]
    ]
    assert result["policy_experiment_application_context"]["run_id"] == "improvement-run"
    assert result["policy_experiment_application_context"]["board_type"] == "ai_news"
    assert result["policy_experiment_application_context"]["applied_policy_experiments"] == []
    assert result["improvement_proposals"][0]["change_type"] == "policy_experiment"
    assert "proposed_patch" not in result["improvement_proposals"][0]
    assert (
        result["self_improvement_report"]["policy_experiment_profiles"]
        == result["policy_experiment_profiles"]
    )


def test_productized_improvement_workflow_uses_formal_run_state_measurement() -> None:
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

    class LegacyBoardRunResult:
        metadata = {
            "deduplication_result": {
                "event_groups": [{"item_ids": ["legacy-1"]}]
            }
        }

    result = service.build_outputs(
        request={
            "run_id": "improvement-run",
            "previous_measurement_baseline": {"duplicate_rate": 0.0},
        },
        board_run_result=LegacyBoardRunResult(),
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        feedback_events=[],
        learning_signals=[],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
        productized_run=productized_run,
    )

    assert result["improvement_measurement"]["duplicate_rate_delta"] == 0.5


def test_productized_improvement_measurement_reads_formal_productized_run_state() -> None:
    service = ProductizedImprovementMeasurementService()
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

    measurement = service.measure(
        previous_baseline={"duplicate_rate": 0.0},
        board_run_result=StubBoardRunResult(),
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
        productized_run=productized_run,
    )

    assert measurement.to_dict()["duplicate_rate_delta"] == 0.5


def test_productized_improvement_measurement_formal_entrypoint_reads_run_state() -> None:
    service = ProductizedImprovementMeasurementService()
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

    measurement = service.measure_productized(
        previous_baseline={"duplicate_rate": 0.0},
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
        productized_run=productized_run,
    )

    assert measurement.to_dict()["duplicate_rate_delta"] == 0.5


def test_productized_improvement_measurement_input_removes_board_metadata_dependency() -> None:
    service = ProductizedImprovementMeasurementService()
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

    measurement = service.measure_input(
        previous_baseline={"duplicate_rate": 0.0},
        measurement_input=ProductizedImprovementMeasurementInput.from_productized_run(
            quality_summary={"score": 0.72},
            cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
            subscription_payload={"targets": [{"topic": "Agent Memory"}]},
            productized_run=productized_run,
        ),
    )

    assert measurement.to_dict()["duplicate_rate_delta"] == 0.5


def test_productized_improvement_measurement_prefers_empty_formal_state_over_legacy_metadata() -> None:
    service = ProductizedImprovementMeasurementService()
    productized_run = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="improvement-run",
        deduplication_result={},
    )

    class LegacyBoardRunResult:
        metadata = {
            "deduplication_result": {
                "event_groups": [{"item_ids": ["legacy-1", "legacy-2"]}]
            }
        }

    measurement = service.measure(
        previous_baseline={"duplicate_rate": 0.0},
        board_run_result=LegacyBoardRunResult(),
        quality_summary={"score": 0.72},
        cards=[{"card_id": "card-1", "evidence_refs": [{"source_id": "source-1"}]}],
        subscription_payload={"targets": [{"topic": "Agent Memory"}]},
        productized_run=productized_run,
    )

    assert measurement.to_dict()["duplicate_rate_delta"] == 0.0


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
