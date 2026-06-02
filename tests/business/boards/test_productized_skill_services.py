from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import (
    ProductizedDeduplicationService,
    ProductizedEntityExtractionService,
    ProductizedSignalPreparationService,
)
from business.boards.productized.models import ProductizedRunState
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType, Signal
from business.foundation.skills import BusinessSkillRuntime


def _prepared_run() -> tuple[list[Signal], ProductizedRunState]:
    preparation = ProductizedSignalPreparationService(
        board_type=BoardType.AI_NEWS,
        skill_runtime=BusinessSkillRuntime(),
        improvement_service=BoardImprovementService(),
    )
    result = preparation.prepare(
        {
            "run_id": "skill-service-run",
            "topic": "Agent Memory",
            "signals": [sample_signal("ai_news")],
        }
    )
    return result["prepared_signals"], result["productized_run"]


def test_productized_entity_extraction_service_updates_run_state() -> None:
    board_signals, productized_run = _prepared_run()
    service = ProductizedEntityExtractionService(skill_runtime=BusinessSkillRuntime())

    result = service.extract(
        request={"run_id": "skill-service-run"},
        board_signals=board_signals,
        productized_run=productized_run,
    )

    assert result["extracted_entities"]
    assert result["extracted_entities"][0]["signal_id"] == board_signals[0].signal_id
    assert any(entity["name"] == "Agent Memory" for entity in result["extracted_entities"][0]["entities"])
    assert result["skill_traces"][-1]["skill_name"] == "entity-extraction"
    assert result["productized_run"].extracted_entities == result["extracted_entities"]
    assert result["productized_run"].skill_traces == result["skill_traces"]


def test_productized_deduplication_service_updates_run_state() -> None:
    board_signals, productized_run = _prepared_run()
    service = ProductizedDeduplicationService(skill_runtime=BusinessSkillRuntime())

    result = service.deduplicate(
        request={"run_id": "skill-service-run"},
        board_signals=board_signals,
        productized_run=productized_run,
    )

    assert result["deduplicated_signals"] == board_signals
    assert result["deduplication_result"]["event_groups"]
    assert result["skill_traces"][-1]["skill_name"] == "event-deduplication"
    assert result["productized_run"].deduplication_result == result["deduplication_result"]
    assert result["productized_run"].skill_traces == result["skill_traces"]
