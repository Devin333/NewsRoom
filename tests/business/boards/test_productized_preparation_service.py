from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import ProductizedSignalPreparationService
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType
from business.foundation.feedback import BoardImprovementContext
from business.foundation.skills import BusinessSkillRuntime


def test_productized_signal_preparation_service_builds_formal_run_state() -> None:
    service = ProductizedSignalPreparationService(
        board_type=BoardType.AI_NEWS,
        skill_runtime=BusinessSkillRuntime(),
        improvement_service=BoardImprovementService(),
    )

    result = service.prepare(
        {
            "run_id": "prep-run",
            "topic": "Agent Memory",
            "signals": [sample_signal("ai_news")],
        }
    )

    assert result["context"].run_context.run_id == "prep-run"
    assert len(result["raw_signals"]) == 1
    assert len(result["prepared_signals"]) == 1
    assert result["source_reliability_results"]
    assert result["skill_traces"][0]["skill_name"] == "source-reliability"
    assert result["productized_run"].run_id == "prep-run"
    assert result["productized_run"].source_reliability_results == result["source_reliability_results"]


def test_productized_signal_preparation_uses_policy_experiment_application_entrypoint() -> None:
    improvement_service = _FormalImprovementService()
    service = ProductizedSignalPreparationService(
        board_type=BoardType.AI_NEWS,
        skill_runtime=BusinessSkillRuntime(),
        improvement_service=improvement_service,
    )

    service.prepare(
        {
            "run_id": "policy-run",
            "topic": "Agent Memory",
            "signals": [sample_signal("ai_news")],
        }
    )

    assert improvement_service.calls == [{"run_id": "policy-run", "board_type": "ai_news"}]


class _FormalImprovementService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def apply_approved_policy_experiments(self, *, run_id: str, board_type: str) -> BoardImprovementContext:
        self.calls.append({"run_id": run_id, "board_type": board_type})
        return BoardImprovementContext(run_id=run_id, board_type=board_type)
