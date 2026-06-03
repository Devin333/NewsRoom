from __future__ import annotations

from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.daily_persistence_projection import (
    daily_run_persistence_input_from_result,
    project_daily_run_output_for_persistence,
)


def test_project_daily_run_output_for_persistence_projects_namespaced_output() -> None:
    result = RunResult(
        run_id="run-1",
        workflow_id="daily-intelligence-agentic",
        workflow_version="1.0",
        status=WorkflowStatus.SUCCEEDED,
        output={
            "report.final": {"title": "Daily"},
            "quality.result": {"decision": "pass"},
            "sources.raw_items": [{"title": "Raw"}],
            "final_report": {"title": "legacy"},
        },
    )

    projected = project_daily_run_output_for_persistence(result)

    assert projected == {
        "final_report": {"title": "Daily"},
        "quality_result": {"decision": "pass"},
        "raw_items": [{"title": "Raw"}],
    }


def test_daily_run_persistence_input_from_result_uses_projected_daily_output() -> None:
    result = RunResult(
        run_id="run-1",
        workflow_id="daily-intelligence-agentic",
        workflow_version="1.0",
        status=WorkflowStatus.SUCCEEDED,
        artifact_dir="artifacts/run-1",
        manifest_path="artifacts/run-1/manifest.json",
        events_path="artifacts/run-1/events.jsonl",
        output={
            "report.final": {"title": "Daily"},
            "quality.result": {"decision": "pass"},
            "sources.raw_items": [{"title": "Raw"}],
            "final_report": {"title": "legacy"},
        },
    )

    input_model = daily_run_persistence_input_from_result(result, profile="live")

    assert input_model.run_id == "run-1"
    assert input_model.profile == "live"
    assert input_model.artifact_dir == "artifacts/run-1"
    assert input_model.final_report == {"title": "Daily"}
    assert input_model.quality_result == {"decision": "pass"}
    assert input_model.raw_items == ({"title": "Raw"},)
