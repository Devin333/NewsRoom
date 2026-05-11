import json

import pytest

from interfaces.services.report_service import ReportApplicationService


def test_report_service_searches_local_report_artifacts(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    result = ReportApplicationService(artifact_root=tmp_path).search_reports(query="policy")

    payload = result.to_dict()
    assert payload["query"] == "policy"
    assert payload["report_count"] == 1
    assert payload["reports"][0]["run_id"] == "run-1"
    assert payload["reports"][0]["title"] == "AI Policy Report"


def test_report_service_rejects_empty_query(tmp_path) -> None:
    service = ReportApplicationService(artifact_root=tmp_path)

    with pytest.raises(ValueError, match="query is required"):
        service.search_reports(query="")


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
