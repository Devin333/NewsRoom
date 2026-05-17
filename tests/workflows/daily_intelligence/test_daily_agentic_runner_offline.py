from __future__ import annotations

import json
from pathlib import Path

from core.framework.specs import WorkflowStatus
from workflows.daily_intelligence import AgenticDailyIntelligenceRunner
from workflows.daily_intelligence.profiles import PROFILE_AGENTIC_OFFLINE


def test_agentic_daily_runner_offline_runs_full_workflow(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-offline-runner",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.workflow_id == "daily-intelligence-agentic"
    assert result.output["research_plan"]["topic"] == "AI policy"
    assert result.output["analysis_result"]["findings"][0]["id"] == "finding-1"
    assert result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert result.output["verification_result"]["status"] == "pass"
    assert result.output["editor_review"]["decision"] == "pass"
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"
    assert "https://example.com/ai-chip-policy" in result.output["report_markdown"]
    assert result.output["planner_agent_loop_result"]["success"] is True
    assert result.output["analyst_agent_loop_result"]["success"] is True
    assert result.output["writer_agent_loop_result"]["success"] is True
    assert result.output["verifier_agent_loop_result"]["success"] is True
    assert result.output["editor_agent_loop_result"]["success"] is True

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == PROFILE_AGENTIC_OFFLINE
    assert manifest["status"] == WorkflowStatus.SUCCEEDED.value
    assert manifest["workflow_id"] == "daily-intelligence-agentic"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"
    assert manifest["quality_route"] == "publish"

    runners_by_step = {runner["step_id"]: runner for runner in manifest["runners"]}
    for step_id in ("planner_agent", "analyst_agent", "writer_agent", "verifier_agent", "editor_agent"):
        assert runners_by_step[step_id]["runner_id"] == "builtin.agent_loop"
        assert runners_by_step[step_id]["step_type"] == "agent_loop"
        assert manifest["steps"][step_id]["status"] == "succeeded"

    event_pairs = {
        (event["event_type"], event["payload"].get("step_id"))
        for event in _events(run_dir / "events.jsonl")
        if event["event_type"] in {"step_started", "step_succeeded"}
    }
    for step_id in ("planner_agent", "analyst_agent", "writer_agent", "verifier_agent", "editor_agent"):
        assert ("step_started", step_id) in event_pairs
        assert ("step_succeeded", step_id) in event_pairs


def _events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
