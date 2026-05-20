import json

import pytest

from infrastructure.storage.local_json import LocalJsonRepository, ReportNotFoundError
from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID


def _write_report_run(
    root,
    run_id: str,
    finished_at: str,
    title: str,
    *,
    workflow_id: str | None = None,
    blocked: bool = False,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    report_name = "blocked_report.json" if blocked else "report.json"
    (run_dir / report_name).write_text(json.dumps({"title": title}), encoding="utf-8")
    (run_dir / "report.md").write_text(f"# {title}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "profile": "live-offline",
                "status": "succeeded",
                "finished_at": finished_at,
                "quality_score": 0.9,
                "artifacts": {
                    ("blocked_report" if blocked else "report_json"): report_name,
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )


def test_local_json_repository_returns_latest_report(tmp_path) -> None:
    _write_report_run(tmp_path, "old", "2026-05-10T00:00:00Z", "Old Report")
    _write_report_run(tmp_path, "new", "2026-05-11T00:00:00Z", "New Report")

    record = LocalJsonRepository(tmp_path).latest_report()

    assert record.report_id == "new:final"
    assert record.run_id == "new"
    assert record.status == "final"
    assert record.title == "New Report"
    assert record.quality_score == 0.9
    assert record.report_json == {"title": "New Report"}
    assert record.report_markdown == "# New Report\n"


def test_local_json_repository_gets_report_by_id(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    record = LocalJsonRepository(tmp_path).get_report("run-1:final")

    assert record.report_id == "run-1:final"
    assert record.run_id == "run-1"
    assert record.status == "final"
    assert record.title == "AI Policy Report"
    assert record.report_json == {"title": "AI Policy Report"}
    assert record.report_markdown == "# AI Policy Report\n"


def test_local_json_repository_gets_blocked_report_by_id(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-blocked",
        "2026-05-11T00:00:00Z",
        "Blocked AI Report",
        blocked=True,
    )

    record = LocalJsonRepository(tmp_path).get_report("run-blocked:blocked")

    assert record.report_id == "run-blocked:blocked"
    assert record.run_id == "run-blocked"
    assert record.status == "blocked"
    assert record.title == "Blocked AI Report"
    assert record.report_json == {"title": "Blocked AI Report"}


def test_local_json_repository_rejects_invalid_report_id(tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid report id"):
        LocalJsonRepository(tmp_path).get_report("../secret:final")


def test_local_json_repository_raises_when_report_id_missing(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    with pytest.raises(ReportNotFoundError, match="report not found"):
        LocalJsonRepository(tmp_path).get_report("missing:final")


def test_local_json_repository_raises_for_non_final_report_id(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    with pytest.raises(ReportNotFoundError, match="report not found"):
        LocalJsonRepository(tmp_path).get_report("run-1:blocked")


def test_local_json_repository_raises_for_wrong_blocked_report_status(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-blocked",
        "2026-05-11T00:00:00Z",
        "Blocked AI Report",
        blocked=True,
    )

    with pytest.raises(ReportNotFoundError, match="report not found"):
        LocalJsonRepository(tmp_path).get_report("run-blocked:final")


def test_local_json_repository_raises_when_missing_report(tmp_path) -> None:
    with pytest.raises(ReportNotFoundError, match="no local report"):
        LocalJsonRepository(tmp_path).latest_report()


def test_local_json_repository_searches_reports(tmp_path) -> None:
    _write_report_run(tmp_path, "old", "2026-05-10T00:00:00Z", "Chip Supply Report")
    _write_report_run(tmp_path, "new", "2026-05-11T00:00:00Z", "AI Policy Report")
    _write_report_run(
        tmp_path,
        "blocked",
        "2026-05-12T00:00:00Z",
        "Blocked Policy Report",
        blocked=True,
    )

    records = LocalJsonRepository(tmp_path).search_reports("policy")

    assert [record.run_id for record in records] == ["blocked", "new"]
    assert records[0].report_id == "blocked:blocked"
    assert records[0].status == "blocked"
    assert records[0].title == "Blocked Policy Report"


def test_local_json_repository_lists_reports_with_workflow_filter(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "daily-old",
        "2026-05-10T00:00:00Z",
        "Old Daily",
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )
    _write_report_run(
        tmp_path,
        "daily-new",
        "2026-05-11T00:00:00Z",
        "New Daily",
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )
    _write_report_run(
        tmp_path,
        "weekly",
        "2026-05-12T00:00:00Z",
        "Weekly",
        workflow_id="weekly-intelligence",
    )

    records = LocalJsonRepository(tmp_path).list_reports(
        limit=10,
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )

    assert [record.run_id for record in records] == ["daily-new", "daily-old"]
    assert records[0].workflow_id == LEGACY_DAILY_WORKFLOW_ID
    assert records[0].profile == "live-offline"


def test_local_json_repository_lists_blocked_reports(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "blocked",
        "2026-05-12T00:00:00Z",
        "Blocked Policy Report",
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
        blocked=True,
    )

    records = LocalJsonRepository(tmp_path).list_reports(limit=10)

    assert records[0].report_id == "blocked:blocked"
    assert records[0].status == "blocked"
    assert records[0].title == "Blocked Policy Report"
