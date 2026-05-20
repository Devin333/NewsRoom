from __future__ import annotations

import json

from framework.artifacts import ArtifactManager
from framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from framework.workflow import ArtifactPublishContext, ArtifactPublishPhase
from workflows.daily_intelligence.artifact_publisher import DailyIntelligenceArtifactPublisher
from workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID


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
        },
    )

    DailyIntelligenceArtifactPublisher().publish(context)

    run_dir = tmp_path / "run-1"
    assert manifest["artifacts"]["raw_items"] == "raw_items.json"
    assert manifest["artifacts"]["source_pipeline_metrics"] == "source_pipeline_metrics.json"
    assert manifest["artifacts"]["source_artifacts"] == "source_artifacts/index.json"
    assert manifest["source_event_count"] == 1
    assert manifest["source_artifacts"]["item_count"] == 1
    assert (run_dir / "source_artifacts" / "index.json").exists()


def _context(
    manager: ArtifactManager,
    *,
    manifest: dict,
    output: dict,
    status: WorkflowStatus = WorkflowStatus.SUCCEEDED,
) -> ArtifactPublishContext:
    return ArtifactPublishContext(
        phase=ArtifactPublishPhase.TERMINAL,
        run_id="run-1",
        workflow=WorkflowSpec(
            workflow_id=LEGACY_DAILY_WORKFLOW_ID,
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
