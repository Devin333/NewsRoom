import json
from pathlib import Path

from core.framework.specs import WorkflowStatus
from workflows.daily_intelligence import run_test_agent_loop


def test_test_agent_loop_workflow_writes_events_and_metrics(tmp_path) -> None:
    result = run_test_agent_loop(
        artifact_root=tmp_path,
        request={"topic": "agentic research"},
        run_id="test-agent-loop-success",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["analysis_result"]["confidence"] == "high"
    assert result.output["agent_loop_metrics"]["llm_calls"] == 3
    assert result.output["agent_loop_metrics"]["tool_calls"] == 1
    assert result.output["agent_loop_metrics"]["token_usage"]["total_tokens"] == 60

    run_dir = Path(result.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "test-agent-loop"
    assert manifest["llm_calls"] == 3
    assert manifest["tool_calls"] == 1
    assert manifest["token_usage"]["total_tokens"] == 60
    assert manifest["artifacts"]["agent_loop_events"] == "agent_loop_events.json"

    agent_events = json.loads((run_dir / "agent_loop_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in agent_events] == [
        "agent_started",
        "llm_call",
        "tool_call",
        "tool_observation",
        "llm_call",
        "judge_retry",
        "llm_call",
        "final_output",
    ]
