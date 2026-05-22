from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from framework.specs import WorkflowStatus

from business.boards.cross_board.profiles import LEGACY_DAILY_WORKFLOW_ID
from business.boards.cross_board.workflows.weekly_intelligence.runner import WeeklyIntelligenceRunner


def test_weekly_productized_acceptance_consumes_persisted_reports(tmp_path) -> None:
    end = datetime(2026, 5, 22, 23, 59, 59, tzinfo=UTC)
    _write_report_fixture(tmp_path, "weekly-productized-daily", finished_at=end - timedelta(days=1))
    _write_report_fixture(tmp_path, "weekly-productized-cross", finished_at=end - timedelta(days=2))

    result = WeeklyIntelligenceRunner(artifact_root=tmp_path).run(
        topic="Agent Memory",
        source_limit=5,
        period_start="2026-05-15T00:00:00Z",
        period_end="2026-05-22T23:59:59Z",
        run_id="weekly-productized-acceptance",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["weekly_trends"]
    assert result.output["weekly_timeline"]
    assert result.output["weekly_quality"]["score"] is not None
    assert result.output["weekly_subscription_payload"]["targets"]
    assert "recommendations" in result.output["weekly_improvement_report"]

    run_dir = Path(result.artifact_dir)
    for file_name in (
        "weekly_trends.json",
        "weekly_timeline.json",
        "weekly_quality.json",
        "weekly_subscription_payload.json",
        "weekly_improvement_report.json",
    ):
        assert (run_dir / file_name).exists(), file_name
        assert json.loads((run_dir / file_name).read_text(encoding="utf-8"))


def _write_report_fixture(root: Path, run_id: str, *, finished_at: datetime) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "title": "Daily Intelligence: Agent Memory",
        "source_urls": ["https://example.com/agent-memory"],
        "sections": [
            {
                "title": "Executive Summary",
                "content": "Agent Memory, OpenAI, LangChain, and MCP appeared in productized board output.",
                "sources": ["https://example.com/agent-memory"],
            }
        ],
        "metadata": {
            "topic": "Agent Memory",
            "cross_board_summary": "Aggregated productized board outputs.",
            "weekly_acceptance_fixture": True,
        },
    }
    manifest = {
        "run_id": run_id,
        "workflow_id": LEGACY_DAILY_WORKFLOW_ID,
        "workflow_version": "0.1.0",
        "profile": "live-offline",
        "status": "succeeded",
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "quality_score": 0.84,
        "artifacts": {"report_json": "report.json", "report_markdown": "report.md"},
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text("# Daily Intelligence: Agent Memory\n\nOffline weekly fixture.\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
