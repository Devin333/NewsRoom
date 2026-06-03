from business.boards.cross_board.workflows.daily_intelligence.agentic_artifact_projection import (
    project_daily_agentic_artifacts,
)


def test_agentic_artifact_projection_builds_artifacts_manifest_and_redacts_llm_payloads() -> None:
    projection = project_daily_agentic_artifacts(
        run_id="run-1",
        workflow_id="daily-intelligence-agentic",
        workflow_version="1.0",
        output={
            "agent.planner.loop.result": {
                "status": "accepted",
                "success": True,
                "llm_call_artifacts": [
                    {
                        "artifact_id": "llm-1",
                        "iteration": 1,
                        "request": {"prompt": "secret prompt"},
                        "response": {"content": "secret response", "usage": {"input_tokens": 4}},
                        "metadata": {"provider": "test"},
                    }
                ],
            },
            "agent.planner.loop.metrics": {"llm_calls": "1", "tool_calls": 0},
            "agent.planner.loop.diagnostics": {"stop_reason": "final_output_accepted"},
            "agent.planner.loop.trace": {"summary": {"stop_reason": "trace_stop"}},
            "agent.planner.loop.llm_call_artifacts": [
                {
                    "artifact_id": "llm-1",
                    "iteration": 1,
                    "request": {"prompt": "secret prompt"},
                    "response": {"content": "secret response", "usage": {"input_tokens": 4}},
                    "metadata": {"provider": "test"},
                }
            ],
            "agent.feedback.events": [{"feedback_id": "feedback-1"}],
            "agent.feedback.summary": {"highest_severity": "warning"},
            "quality.result": {"decision": "rewrite_required", "quality_score": 0.72},
        },
    )

    artifacts = {artifact.artifact_key: artifact for artifact in projection.artifacts}

    assert projection.manifest_fields["agentic"] is True
    assert projection.manifest_fields["agent_count"] == 5
    assert projection.manifest_fields["agent_steps"] == [
        "planner_agent",
        "analyst_agent",
        "writer_agent",
        "verifier_agent",
        "editor_agent",
    ]
    assert projection.manifest_fields["agent_feedback"] == {
        "event_count": 1,
        "highest_severity": "warning",
        "artifact": "agentic/agent_feedback_summary.json",
    }
    assert projection.manifest_fields["agentic_summary"] == {
        "agent_count": 5,
        "final_decision": "rewrite_required",
        "quality_score": 0.72,
        "artifact": "agentic_summary.json",
    }

    assert artifacts["planner_agent_loop_result"].relative_path == (
        "agentic/planner_agent_loop_result.json"
    )
    redacted_result = artifacts["planner_agent_loop_result"].payload
    assert redacted_result["llm_call_artifacts"] == [
        {
            "artifact_id": "llm-1",
            "iteration": 1,
            "metadata": {"provider": "test"},
            "artifact_ref": None,
            "usage": {"input_tokens": 4},
            "redacted": True,
        }
    ]

    assert artifacts["planner_llm_call_artifacts"].payload == [
        {
            "artifact_id": "llm-1",
            "iteration": 1,
            "metadata": {"provider": "test"},
            "artifact_ref": None,
            "usage": {"input_tokens": 4},
            "redacted": True,
        }
    ]
    assert artifacts["agentic_summary"].payload["feedback_event_count"] == 1
    planner_summary = artifacts["agentic_summary"].payload["agents"][0]
    assert planner_summary["step_id"] == "planner_agent"
    assert planner_summary["status"] == "accepted"
    assert planner_summary["llm_calls"] == 1
    assert planner_summary["llm_artifact_count"] == 1


def test_agentic_artifact_projection_handles_legacy_loop_keys() -> None:
    projection = project_daily_agentic_artifacts(
        run_id="run-1",
        workflow_id="daily-intelligence-agentic",
        workflow_version="1.0",
        output={
            "planner_agent_loop_result": {"success": False},
            "quality_result": {"decision": "blocked"},
        },
    )

    artifacts = {artifact.artifact_key: artifact for artifact in projection.artifacts}

    assert "planner_agent_loop_result" in artifacts
    assert artifacts["agentic_summary"].payload["final_decision"] == "blocked"
    assert artifacts["agentic_summary"].payload["agents"][0]["status"] == "failed"


def test_agentic_artifact_projection_prefers_namespaced_values_over_legacy() -> None:
    projection = project_daily_agentic_artifacts(
        run_id="run-1",
        workflow_id="daily-intelligence-agentic",
        workflow_version="1.0",
        output={
            "planner_agent_loop_result": {"status": "legacy", "success": False},
            "agent.planner.loop.result": {"status": "accepted", "success": True},
            "agent_feedback_summary": {"highest_severity": "legacy"},
            "agent.feedback.summary": {"highest_severity": "warning"},
            "quality_result": {"decision": "legacy"},
            "quality.result": {"decision": "rewrite_required", "quality_score": 0.8},
        },
    )

    artifacts = {artifact.artifact_key: artifact for artifact in projection.artifacts}

    assert artifacts["planner_agent_loop_result"].payload["status"] == "accepted"
    assert projection.manifest_fields["agent_feedback"]["highest_severity"] == "warning"
    assert artifacts["agentic_summary"].payload["final_decision"] == "rewrite_required"
    assert artifacts["agentic_summary"].payload["quality_score"] == 0.8
