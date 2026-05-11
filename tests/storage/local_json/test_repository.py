import json

import pytest

from storage.local_json import LocalJsonRepository, ReportNotFoundError


def _write_report_run(root, run_id: str, finished_at: str, title: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(json.dumps({"title": title}), encoding="utf-8")
    (run_dir / "report.md").write_text(f"# {title}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "succeeded",
                "finished_at": finished_at,
                "artifacts": {
                    "report_json": "report.json",
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

    assert record.run_id == "new"
    assert record.report_json == {"title": "New Report"}
    assert record.report_markdown == "# New Report\n"


def test_local_json_repository_raises_when_missing_report(tmp_path) -> None:
    with pytest.raises(ReportNotFoundError, match="no local report"):
        LocalJsonRepository(tmp_path).latest_report()


def test_local_json_repository_searches_reports(tmp_path) -> None:
    _write_report_run(tmp_path, "old", "2026-05-10T00:00:00Z", "Chip Supply Report")
    _write_report_run(tmp_path, "new", "2026-05-11T00:00:00Z", "AI Policy Report")

    records = LocalJsonRepository(tmp_path).search_reports("policy")

    assert [record.run_id for record in records] == ["new"]
    assert records[0].title == "AI Policy Report"
