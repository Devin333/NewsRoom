from __future__ import annotations

from business.boards._improvement import BoardImprovementService
from business.boards.productized import ProductizedSignalPreparationService
from business.boards.productized.workflow import build_productized_board_workflow
from business.evaluation.fixtures import sample_signal
from business.foundation import BoardType
from business.foundation.feedback import PolicyExperimentApplicationContext
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
    assert result["policy_experiment_application_context"]["run_id"] == "prep-run"
    assert (
        result["productized_run"].improvement_context
        == result["policy_experiment_application_context"]
    )
    assert result["improvement_context"] == result["policy_experiment_application_context"]


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


def test_productized_prepare_step_declares_policy_experiment_application_context() -> None:
    workflow = build_productized_board_workflow(BoardType.AI_NEWS)
    write_keys_by_step = {step.step_id: step.write_keys for step in workflow.steps}

    assert "policy_experiment_application_context" in write_keys_by_step[
        "prepare_signals"
    ]
    assert "improvement_context" in write_keys_by_step["prepare_signals"]


class _FormalImprovementService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def apply_approved_policy_experiments(
        self,
        *,
        run_id: str,
        board_type: str,
    ) -> PolicyExperimentApplicationContext:
        self.calls.append({"run_id": run_id, "board_type": board_type})
        return PolicyExperimentApplicationContext(run_id=run_id, board_type=board_type)
