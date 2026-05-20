from __future__ import annotations

import json
from pathlib import Path

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import AgenticDailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_OFFLINE


def test_agentic_daily_artifacts_include_agent_summary_and_loop_outputs(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-artifacts",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    run_dir = Path(result.artifact_dir)
    manifest = _read_json(run_dir / "manifest.json")

    assert manifest["agentic"] is True
    assert manifest["agent_count"] == 5
    assert manifest["agent_steps"] == [
        "planner_agent",
        "analyst_agent",
        "writer_agent",
        "verifier_agent",
        "editor_agent",
    ]
    assert manifest["artifacts"]["agentic_summary"] == "agentic_summary.json"
    assert manifest["agentic_summary"]["agent_count"] == 5
    assert manifest["agentic_summary"]["final_decision"] == "pass"

    summary = _read_json(run_dir / "agentic_summary.json")
    assert summary["run_id"] == "agentic-artifacts"
    assert summary["workflow_id"] == "daily-intelligence-agentic"
    assert summary["agent_count"] == 5
    assert summary["final_decision"] == "pass"
    assert summary["quality_score"] == 1.0

    agents_by_step = {agent["step_id"]: agent for agent in summary["agents"]}
    assert set(agents_by_step) == {
        "planner_agent",
        "analyst_agent",
        "writer_agent",
        "verifier_agent",
        "editor_agent",
    }
    assert agents_by_step["planner_agent"]["agent_id"] == "daily.planner"
    assert agents_by_step["analyst_agent"]["agent_id"] == "daily.analyst"
    assert agents_by_step["writer_agent"]["agent_id"] == "daily.writer"
    assert agents_by_step["verifier_agent"]["agent_id"] == "daily.verifier"
    assert agents_by_step["editor_agent"]["agent_id"] == "daily.editor"

    for step_id, label in [
        ("planner_agent", "planner"),
        ("analyst_agent", "analyst"),
        ("writer_agent", "writer"),
        ("verifier_agent", "verifier"),
        ("editor_agent", "editor"),
    ]:
        agent = agents_by_step[step_id]
        assert agent["status"] == "accepted"
        assert agent["success"] is True
        assert agent["llm_calls"] == 1
        assert agent["tool_calls"] == 0
        assert agent["diagnostics_present"] is True
        assert agent["trace_present"] is True
        assert agent["llm_artifact_count"] == 1

        assert manifest["artifacts"][f"{label}_agent_loop_result"] == (
            f"agentic/{label}_agent_loop_result.json"
        )
        assert manifest["artifacts"][f"{label}_agent_loop_metrics"] == (
            f"agentic/{label}_agent_loop_metrics.json"
        )
        assert manifest["artifacts"][f"{label}_agent_loop_diagnostics"] == (
            f"agentic/{label}_agent_loop_diagnostics.json"
        )
        assert manifest["artifacts"][f"{label}_agent_loop_trace"] == (
            f"agentic/{label}_agent_loop_trace.json"
        )
        assert manifest["artifacts"][f"{label}_llm_call_artifacts"] == (
            f"agentic/{label}_llm_call_artifacts.json"
        )

        loop_result = _read_json(run_dir / f"agentic/{label}_agent_loop_result.json")
        metrics = _read_json(run_dir / f"agentic/{label}_agent_loop_metrics.json")
        diagnostics = _read_json(run_dir / f"agentic/{label}_agent_loop_diagnostics.json")
        trace = _read_json(run_dir / f"agentic/{label}_agent_loop_trace.json")
        llm_artifacts = _read_json(run_dir / f"agentic/{label}_llm_call_artifacts.json")

        assert loop_result["success"] is True
        assert metrics["llm_calls"] == 1
        assert diagnostics["severity"] == "ok"
        assert diagnostics["summary"] == "agent output accepted"
        assert trace["summary"]["llm_call_count"] == 1
        assert len(llm_artifacts) == 1
        assert llm_artifacts[0]["redacted"] is True
        assert "prompt" not in llm_artifacts[0]
        assert "request" not in llm_artifacts[0]
        assert "response" not in llm_artifacts[0]
        assert "request" not in loop_result["llm_call_artifacts"][0]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
