from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import (
    ProductizedDeduplicationService,
    ProductizedEntityExtractionService,
    ProductizedQualitySummaryService,
    ProductizedSignalPreparationService,
    ProductizedTrendAnalysisService,
)
from business.boards.productized.models import ProductizedRunState
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType, Signal
from business.foundation.skills import BusinessSkillRuntime


class StubCard:
    def __init__(self, summary: str) -> None:
        self.summary = summary


class StubQualitySummary:
    def to_dict(self) -> dict[str, object]:
        return {"status": "passed", "score": 0.82}


class StubBoardRunResult:
    cards = [StubCard("Agent Memory improves workflow orchestration.")]
    quality_summary = StubQualitySummary()


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


def test_productized_trend_analysis_service_updates_run_state() -> None:
    board_signals, productized_run = _prepared_run()
    productized_run = productized_run.with_updates(
        deduplication_result={
            "event_groups": [
                {
                    "event_id": "event-agent-memory",
                    "item_ids": [board_signals[0].signal_id],
                    "canonical_item_id": board_signals[0].signal_id,
                }
            ]
        }
    )
    service = ProductizedTrendAnalysisService(skill_runtime=BusinessSkillRuntime())

    result = service.analyze(
        request={"run_id": "skill-service-run"},
        ranked_signals=board_signals,
        productized_run=productized_run,
    )

    assert result["trend_analysis"]["event_analyses"]
    assert result["skill_traces"][-1]["skill_name"] == "trend-analysis"
    assert result["productized_run"].trend_analysis == result["trend_analysis"]
    assert result["productized_run"].skill_traces == result["skill_traces"]


def test_productized_quality_summary_service_updates_run_state() -> None:
    productized_run = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="quality-service-run",
        skill_traces=[{"skill_name": "existing"}],
        evidence_refs=[{"source_id": "source-1"}],
        evidence_items=[
            {
                "source_id": "source-1",
                "summary": "Agent Memory evidence supports the board card.",
                "url": "https://example.com/agent-memory",
            }
        ],
    )
    service = ProductizedQualitySummaryService(skill_runtime=BusinessSkillRuntime())

    result = service.build_summary(
        request={"run_id": "quality-service-run"},
        board_run_result=StubBoardRunResult(),
        productized_run=productized_run,
    )

    assert result["quality_summary"]["score"] == 0.82
    assert result["quality_summary"]["evidence_checking"]["claim_results"]
    assert result["evidence_checking"] == result["quality_summary"]["evidence_checking"]
    assert result["skill_traces"][-1]["skill_name"] == "evidence-checking"
    assert result["productized_run"].skill_traces == result["skill_traces"]
