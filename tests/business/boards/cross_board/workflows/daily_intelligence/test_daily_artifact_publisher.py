from __future__ import annotations

import json

from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
    DailyIntelligenceArtifactPublisher,
)
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    LEGACY_DAILY_WORKFLOW_ID,
)
from business.boards.cross_board.workflows.daily_intelligence.spec_agentic import (
    AGENTIC_WORKFLOW_ID,
)
from framework.artifacts import ArtifactManager
from framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from framework.workflow import ArtifactPublishContext, ArtifactPublishPhase


def test_daily_artifact_publisher_writes_report_and_quality_manifest(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    output = {
        "evidence_bundle": {
            "bundle_id": "bundle-1",
            "source_map": {"ev-1": ["https://example.com/source"]},
            "items": [
                {
                    "evidence_id": "ev-1",
                    "title": "Source item",
                    "source_url": "https://example.com/source",
                }
            ],
        },
        "citation_check_result": {
            "passed": True,
            "unsupported_claims": [],
            "rejected_claim_usage": [],
            "failure_categories": [],
            "section_results": [],
        },
        "quality_result": {"decision": "pass", "route": "final"},
        "final_report": {"title": "Daily Intelligence", "sections": []},
        "report_markdown": "# Daily Intelligence",
    }
    context = _context(
        manager,
        manifest=manifest,
        output=output,
    )

    refs = DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert {ref.artifact_id for ref in refs} >= {
        "evidence_bundle",
        "evidence_source_map",
        "citation_check_result",
        "quality_result",
        "report_json",
        "report_markdown",
    }
    assert (run_dir / "evidence_bundle.json").exists()
    assert (run_dir / "citation_check_result.json").exists()
    assert (run_dir / "quality_result.json").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()
    assert (
        json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["title"]
        == "Daily Intelligence"
    )
    assert (run_dir / "report.md").read_text(encoding="utf-8") == "# Daily Intelligence"
    assert manifest["artifacts"]["evidence_bundle"] == "evidence_bundle.json"
    assert manifest["artifacts"]["citation_check_result"] == "citation_check_result.json"
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert manifest["quality_route"] == "final"
    assert manifest["quality_decision"] == "pass"


def test_daily_artifact_publisher_reads_namespaced_report_and_quality_output(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    output = {
        "evidence.bundle": {
            "bundle_id": "bundle-1",
            "source_map": {"ev-1": ["https://example.com/source"]},
            "items": [
                {
                    "evidence_id": "ev-1",
                    "title": "Source item",
                    "source_url": "https://example.com/source",
                }
            ],
        },
        "quality.citation_check_result": {
            "passed": True,
            "unsupported_claims": [],
            "rejected_claim_usage": [],
            "failure_categories": [],
            "section_results": [],
        },
        "quality.result": {"decision": "pass", "route": "final"},
        "report.final": {"title": "Daily Intelligence", "sections": []},
        "report.markdown": "# Daily Intelligence",
    }
    context = _context(
        manager,
        manifest=manifest,
        output=output,
    )

    refs = DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert {ref.artifact_id for ref in refs} >= {
        "evidence_bundle",
        "evidence_source_map",
        "citation_check_result",
        "quality_result",
        "report_json",
        "report_markdown",
    }
    assert (run_dir / "evidence_bundle.json").exists()
    assert (run_dir / "citation_check_result.json").exists()
    assert (run_dir / "quality_result.json").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()
    assert manifest["artifacts"]["evidence_bundle"] == "evidence_bundle.json"
    assert manifest["artifacts"]["citation_check_result"] == "citation_check_result.json"
    assert manifest["artifacts"]["quality_result"] == "quality_result.json"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert manifest["quality_route"] == "final"
    assert manifest["quality_decision"] == "pass"


def test_daily_artifact_publisher_prefers_namespaced_quality_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    output = {
        "citation_check_result": {
            "unsupported_claims": ["legacy claim"],
            "rejected_claim_usage": [],
        },
        "quality.citation_check_result": {
            "unsupported_claims": ["namespaced claim"],
            "rejected_claim_usage": [],
        },
        "quality.result": {"decision": "blocked", "route": "human_review"},
        "quality.gate_metrics": {"blocked": True},
    }
    context = _context(
        manager,
        manifest=manifest,
        output=output,
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    citation_check = json.loads(
        (run_dir / "citation_check_result.json").read_text(encoding="utf-8")
    )
    unsupported_claims = json.loads(
        (run_dir / "unsupported_claims.json").read_text(encoding="utf-8")
    )
    quality_gate_metrics = json.loads(
        (run_dir / "quality_gate_metrics.json").read_text(encoding="utf-8")
    )

    assert citation_check["unsupported_claims"] == ["namespaced claim"]
    assert unsupported_claims == ["namespaced claim"]
    assert quality_gate_metrics == {"blocked": True}
    assert manifest["quality_decision"] == "blocked"
    assert manifest["quality_route"] == "human_review"


def test_daily_artifact_publisher_prefers_namespaced_report_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    output = {
        "final_report": {"title": "Legacy", "sections": []},
        "report.final": {"title": "Namespaced", "sections": []},
        "report_markdown": "# Legacy",
        "report.markdown": "# Namespaced",
    }
    context = _context(
        manager,
        manifest=manifest,
        output=output,
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert (
        json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["title"]
        == "Namespaced"
    )
    assert (run_dir / "report.md").read_text(encoding="utf-8") == "# Namespaced"


def test_daily_artifact_publisher_writes_blocked_report_even_on_succeeded_status(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        output={
            "blocked_report": {"status": "blocked", "reasons": ["quality"]},
            "quality_result": {"route": "human_review", "decision": "blocked"},
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert json.loads((run_dir / "blocked_report.json").read_text(encoding="utf-8"))[
        "status"
    ] == "blocked"
    assert manifest["artifacts"]["blocked_report"] == "blocked_report.json"
    assert manifest["quality_route"] == "human_review"
    assert manifest["quality_decision"] == "blocked"


def test_daily_artifact_publisher_writes_source_diagnostics(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        output={
            "raw_items": [
                {
                    "source_id": "feed",
                    "source_item_id": "item-1",
                    "title": "Item",
                    "url": "https://example.com/item",
                    "raw_content": "raw",
                }
            ],
            "source_errors": [],
            "source_fetch_requests": [{"request_id": "req-1", "source_id": "feed"}],
            "source_fetch_results": [{"request_id": "req-1", "source_id": "feed", "success": True}],
            "source_events": [{"event_type": "source_fetch_succeeded"}],
            "source_pipeline_metrics": {"raw_items_count": 1},
            "source_recollection_profile": {"profile_id": "profile-1", "query_count": 1},
            "source_recollection_execution_plan": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "task_count": 1,
            },
            "source_recollection_execution_report": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "status": "succeeded",
                "task_count": 1,
                "raw_item_count": 1,
                "error_count": 0,
                "fetch_request_count": 1,
                "fetch_result_count": 1,
                "tasks": [],
            },
            "source_recollection_quality_assessment": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "decision": "pass",
                "severity": "info",
                "route": "continue_source_pipeline",
                "recommended_action": "continue_source_pipeline",
                "failed_thresholds": [],
                "issues": [],
            },
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert manifest["artifacts"]["raw_items"] == "raw_items.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert (
        manifest["artifacts"]["source_recollection_profile"]
        == "source_recollection/profile.json"
    )
    assert (
        manifest["artifacts"]["source_recollection_execution_plan"]
        == "source_recollection/execution_plan.json"
    )
    assert (
        manifest["artifacts"]["source_recollection_execution_report"]
        == "source_recollection/execution_report.json"
    )
    assert (
        manifest["artifacts"]["source_recollection_quality_assessment"]
        == "source_recollection/quality_assessment.json"
    )
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 1
    assert manifest["source_recollection"] == {
        "plan_id": "plan-1",
        "status": "succeeded",
        "task_count": 1,
        "raw_item_count": 1,
        "error_count": 0,
        "fetch_request_count": 1,
        "fetch_result_count": 1,
        "artifact": "source_recollection/execution_report.json",
        "profile_artifact": "source_recollection/profile.json",
        "plan_artifact": "source_recollection/execution_plan.json",
        "quality": {
            "decision": "pass",
            "severity": "info",
            "route": "continue_source_pipeline",
            "recommended_action": "continue_source_pipeline",
            "artifact": "source_recollection/quality_assessment.json",
        },
    }
    assert manifest["source_artifacts"]["item_count"] == 1
    assert (run_dir / "source_artifacts" / "index.json").exists()
    assert (run_dir / "source_recollection" / "profile.json").exists()
    report = json.loads(
        (run_dir / "source_recollection" / "execution_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "succeeded"
    assessment = json.loads(
        (run_dir / "source_recollection" / "quality_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    assert assessment["route"] == "continue_source_pipeline"


def test_daily_artifact_publisher_reads_namespaced_source_diagnostics(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        output={
            "sources.raw_items": [
                {
                    "source_id": "feed",
                    "source_item_id": "item-1",
                    "title": "Item",
                    "url": "https://example.com/item",
                    "raw_content": "raw",
                }
            ],
            "sources.errors": [],
            "sources.fetch_requests": [{"request_id": "req-1", "source_id": "feed"}],
            "sources.fetch_results": [
                {"request_id": "req-1", "source_id": "feed", "success": True}
            ],
            "sources.events": [{"event_type": "source_fetch_succeeded"}],
            "sources.pipeline_metrics": {"raw_items_count": 1},
            "sources.recollection_profile": {"profile_id": "profile-1", "query_count": 1},
            "sources.recollection_execution_plan": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "task_count": 1,
            },
            "sources.recollection_execution_report": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "status": "succeeded",
                "task_count": 1,
                "raw_item_count": 1,
                "error_count": 0,
                "fetch_request_count": 1,
                "fetch_result_count": 1,
                "tasks": [],
            },
            "sources.recollection_quality_assessment": {
                "plan_id": "plan-1",
                "profile_id": "profile-1",
                "decision": "pass",
                "severity": "info",
                "route": "continue_source_pipeline",
                "recommended_action": "continue_source_pipeline",
                "failed_thresholds": [],
                "issues": [],
            },
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert manifest["artifacts"]["raw_items"] == "raw_items.json"
    assert manifest["artifacts"]["source_errors"] == "source_errors.json"
    assert manifest["artifacts"]["source_fetch_requests"] == "source_fetch_requests.json"
    assert manifest["artifacts"]["source_fetch_results"] == "source_fetch_results.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert (
        manifest["artifacts"]["source_recollection_profile"]
        == "source_recollection/profile.json"
    )
    assert (
        manifest["artifacts"]["source_recollection_execution_report"]
        == "source_recollection/execution_report.json"
    )
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 1
    assert manifest["source_recollection"]["status"] == "succeeded"
    assert (
        manifest["source_recollection"]["quality"]["route"]
        == "continue_source_pipeline"
    )
    assert manifest["source_artifacts"]["item_count"] == 1
    assert (run_dir / "source_artifacts" / "index.json").exists()
    assert (run_dir / "source_recollection" / "execution_report.json").exists()


def test_daily_artifact_publisher_writes_agent_feedback_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        workflow_id=AGENTIC_WORKFLOW_ID,
        output={
            "agent_feedback_events": [
                {
                    "feedback_id": "feedback-1",
                    "requested_action": "rewrite",
                }
            ],
            "agent_feedback_summary": {
                "event_count": 1,
                "rewrite_request_count": 1,
                "highest_severity": "warning",
            },
            "quality_result": {"decision": "rewrite_required", "route": "rewrite"},
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    summary = json.loads(
        (run_dir / "agentic" / "agent_feedback_summary.json").read_text(
            encoding="utf-8"
        )
    )
    agentic_summary = json.loads(
        (run_dir / "agentic_summary.json").read_text(encoding="utf-8")
    )

    assert manifest["artifacts"]["agent_feedback_events"] == "agentic/agent_feedback_events.json"
    assert manifest["artifacts"]["agent_feedback_summary"] == "agentic/agent_feedback_summary.json"
    assert manifest["agent_feedback"]["event_count"] == 1
    assert summary["highest_severity"] == "warning"
    assert agentic_summary["feedback_event_count"] == 1


def test_daily_artifact_publisher_reads_namespaced_agent_feedback_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        workflow_id=AGENTIC_WORKFLOW_ID,
        output={
            "agent.feedback.events": [
                {
                    "feedback_id": "feedback-1",
                    "requested_action": "rewrite",
                }
            ],
            "agent.feedback.summary": {
                "event_count": 1,
                "rewrite_request_count": 1,
                "highest_severity": "warning",
            },
            "quality.result": {"decision": "rewrite_required", "route": "rewrite"},
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    summary = json.loads(
        (run_dir / "agentic" / "agent_feedback_summary.json").read_text(
            encoding="utf-8"
        )
    )
    agentic_summary = json.loads(
        (run_dir / "agentic_summary.json").read_text(encoding="utf-8")
    )

    assert manifest["artifacts"]["agent_feedback_events"] == "agentic/agent_feedback_events.json"
    assert manifest["artifacts"]["agent_feedback_summary"] == "agentic/agent_feedback_summary.json"
    assert manifest["agent_feedback"]["event_count"] == 1
    assert summary["highest_severity"] == "warning"
    assert agentic_summary["final_decision"] == "rewrite_required"
    assert agentic_summary["feedback_event_count"] == 1


def test_daily_artifact_publisher_reads_namespaced_agent_loop_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")
    manifest = {"artifacts": {}}
    context = _context(
        manager,
        manifest=manifest,
        workflow_id=AGENTIC_WORKFLOW_ID,
        output={
            "agent.planner.loop.result": {
                "status": "accepted",
                "success": True,
                "llm_call_artifacts": [
                    {
                        "artifact_id": "llm-1",
                        "iteration": 1,
                        "request": {"prompt": "redacted"},
                        "response": {"usage": {"input_tokens": 4}},
                    }
                ],
            },
            "agent.planner.loop.metrics": {"llm_calls": 1, "tool_calls": 0},
            "agent.planner.loop.diagnostics": {
                "severity": "ok",
                "summary": "agent output accepted",
            },
            "agent.planner.loop.trace": {
                "summary": {"stop_reason": "final_output_accepted"}
            },
            "agent.planner.loop.llm_call_artifacts": [
                {
                    "artifact_id": "llm-1",
                    "iteration": 1,
                    "request": {"prompt": "redacted"},
                    "response": {"usage": {"input_tokens": 4}},
                }
            ],
            "quality.result": {"decision": "pass", "route": "final"},
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    loop_result = json.loads(
        (run_dir / "agentic" / "planner_agent_loop_result.json").read_text(
            encoding="utf-8"
        )
    )
    agentic_summary = json.loads(
        (run_dir / "agentic_summary.json").read_text(encoding="utf-8")
    )

    assert manifest["artifacts"]["planner_agent_loop_result"] == (
        "agentic/planner_agent_loop_result.json"
    )
    assert manifest["artifacts"]["planner_agent_loop_metrics"] == (
        "agentic/planner_agent_loop_metrics.json"
    )
    assert manifest["artifacts"]["planner_agent_loop_diagnostics"] == (
        "agentic/planner_agent_loop_diagnostics.json"
    )
    assert manifest["artifacts"]["planner_agent_loop_trace"] == (
        "agentic/planner_agent_loop_trace.json"
    )
    assert manifest["artifacts"]["planner_llm_call_artifacts"] == (
        "agentic/planner_llm_call_artifacts.json"
    )
    assert loop_result["llm_call_artifacts"][0]["redacted"] is True
    assert "request" not in loop_result["llm_call_artifacts"][0]
    planner_summary = next(
        agent
        for agent in agentic_summary["agents"]
        if agent["step_id"] == "planner_agent"
    )
    assert planner_summary["status"] == "accepted"
    assert planner_summary["llm_calls"] == 1
    assert planner_summary["diagnostics_present"] is True
    assert planner_summary["trace_present"] is True
    assert planner_summary["llm_artifact_count"] == 1


def _context(
    manager: ArtifactManager,
    *,
    manifest: dict,
    output: dict,
    status: WorkflowStatus = WorkflowStatus.SUCCEEDED,
    workflow_id: str = LEGACY_DAILY_WORKFLOW_ID,
) -> ArtifactPublishContext:
    return ArtifactPublishContext(
        phase=ArtifactPublishPhase.TERMINAL,
        run_id="run-1",
        workflow=WorkflowSpec(
            workflow_id=workflow_id,
            name="Daily",
            version="1.0",
            start_step_id="start",
            steps=[StepSpec("start", "daily.start")],
        ),
        profile="live-offline",
        status=status,
        request={"topic": "AI"},
        output=output,
        manifest=manifest,
        artifact_manager=manager,
        step_results={},
        path=[],
    )
