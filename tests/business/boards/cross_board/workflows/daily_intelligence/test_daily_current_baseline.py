from __future__ import annotations

import json
from pathlib import Path

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import DailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID, PROFILE_LIVE_OFFLINE


def test_legacy_live_offline_daily_workflow_baseline(tmp_path) -> None:
    result = DailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=2,
        run_id="legacy-live-offline-baseline",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["report_draft"]
    assert result.output["quality_result"]
    assert result.output["quality_gate_metrics"]
    assert result.output["final_report"]
    assert result.output["report_markdown"]

    run_dir = Path(result.artifact_dir)
    assert run_dir.exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "events.jsonl").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow_id"] == LEGACY_DAILY_WORKFLOW_ID
    assert manifest["profile"] == PROFILE_LIVE_OFFLINE
    assert manifest["status"] == WorkflowStatus.SUCCEEDED.value
    assert manifest["artifacts"]["manifest"] == "manifest.json"
    assert manifest["artifacts"]["events"] == "events.jsonl"
    assert manifest["artifacts"]["report_markdown"] == "report.md"

    event_lines = [
        line
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert event_lines
