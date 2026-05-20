import json
from pathlib import Path

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import DailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID
from business.boards.cross_board.workflows.weekly_intelligence import WeeklyIntelligenceRunner


def test_weekly_intelligence_runner_writes_report_from_daily_artifacts(tmp_path) -> None:
    daily = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        run_id="daily-source",
    )
    assert daily.status == WorkflowStatus.SUCCEEDED

    weekly = WeeklyIntelligenceRunner(artifact_root=tmp_path).run(
        topic="AI policy",
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-20T00:00:00Z",
        run_id="weekly-source",
    )

    assert weekly.status == WorkflowStatus.SUCCEEDED
    assert weekly.output["final_report"].title == "Weekly Intelligence: AI policy"
    assert weekly.output["weekly_metrics"]["source_report_count"] == 1
    assert weekly.output["final_report"].metadata["source_report_ids"] == ["daily-source:final"]

    run_dir = Path(weekly.artifact_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert manifest["workflow_id"] == "weekly-intelligence"
    assert manifest["artifacts"]["report_json"] == "report.json"
    assert manifest["artifacts"]["report_markdown"] == "report.md"
    assert report["metadata"]["source_report_count"] == 1
    assert "https://example.com/ai-chip-policy" in report["source_urls"]


def test_weekly_intelligence_runner_reads_daily_workflow_family(tmp_path) -> None:
    daily = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        run_id="daily-source",
    )
    assert daily.status == WorkflowStatus.SUCCEEDED

    weekly = WeeklyIntelligenceRunner(artifact_root=tmp_path).run(
        topic="AI policy",
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-20T00:00:00Z",
        run_id="weekly-source-family",
    )

    assert weekly.status == WorkflowStatus.SUCCEEDED
    assert weekly.output["final_report"].metadata["source_workflow_id"] == LEGACY_DAILY_WORKFLOW_ID


def test_weekly_intelligence_runner_fails_without_daily_reports(tmp_path) -> None:
    result = WeeklyIntelligenceRunner(artifact_root=tmp_path).run(
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-20T00:00:00Z",
        run_id="weekly-empty",
    )

    assert result.status == WorkflowStatus.FAILED
    assert "no eligible daily reports" in result.error["message"]
    manifest = json.loads((Path(result.artifact_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert "report_json" not in manifest["artifacts"]
