from framework.workflow.runtime.run_result import RunResult
from framework.specs import StepType, WorkflowStatus
from framework.workflow import FunctionStepRegistry
import business.boards.cross_board.workflows.daily_intelligence.runner as daily_runner_module
import business.boards.cross_board.workflows.weekly_intelligence.runner as weekly_runner_module


def test_daily_and_weekly_wrappers_share_workflow_runner_assembly_contract(
    tmp_path,
    monkeypatch,
) -> None:
    calls = []

    class CapturingWorkflowRunner:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            calls.append({"init_kwargs": kwargs})

        def run(self, workflow, request, *, profile, run_id=None):
            calls[-1].update(
                {
                    "workflow": workflow,
                    "request": request,
                    "profile": profile,
                    "run_id": run_id,
                }
            )
            return RunResult(
                run_id=run_id or "captured",
                workflow_id=workflow.workflow_id,
                workflow_version=workflow.version,
                status=WorkflowStatus.SUCCEEDED,
                output={},
            )

    monkeypatch.setattr(daily_runner_module, "WorkflowRunner", CapturingWorkflowRunner)
    monkeypatch.setattr(weekly_runner_module, "WorkflowRunner", CapturingWorkflowRunner)

    daily_runner_module.DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=daily_runner_module.PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="daily-contract",
    )
    weekly_runner_module.WeeklyIntelligenceRunner(artifact_root=tmp_path).run(
        topic="AI policy",
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-20T00:00:00Z",
        run_id="weekly-contract",
    )

    assert len(calls) == 2
    for call in calls:
        assert {
            "artifact_root",
            "artifact_publishers",
            "function_registry",
        }.issubset(call["init_kwargs"])
        assert set(call["init_kwargs"]) <= {
            "artifact_root",
            "artifact_publishers",
            "artifact_ref_extractors",
            "function_registry",
            "lineage_extractors",
            "routing_engine",
        }
        assert call["init_kwargs"]["artifact_root"] == tmp_path
        assert isinstance(call["init_kwargs"]["function_registry"], FunctionStepRegistry)
        assert call["init_kwargs"]["artifact_publishers"] is not None
        assert {step.step_type for step in call["workflow"].steps} == {StepType.FUNCTION}

    daily_call, weekly_call = calls
    assert daily_call["workflow"].workflow_id == daily_runner_module.WORKFLOW_ID
    assert daily_call["profile"] == daily_runner_module.PROFILE_LIVE_OFFLINE
    assert daily_call["request"]["profile"] == daily_runner_module.PROFILE_LIVE_OFFLINE
    assert weekly_call["workflow"].workflow_id == weekly_runner_module.WORKFLOW_ID
    assert weekly_call["profile"] == weekly_runner_module.PROFILE_WEEKLY
    assert weekly_call["request"]["source_workflow_id"] == daily_runner_module.WORKFLOW_ID
