import json

import pytest

from interfaces.services.report_service import ReportApplicationService
from workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID


def test_report_service_searches_local_report_artifacts(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    result = ReportApplicationService(artifact_root=tmp_path).search_reports(query="policy")

    payload = result.to_dict()
    assert payload["query"] == "policy"
    assert payload["report_count"] == 1
    assert payload["reports"][0]["run_id"] == "run-1"
    assert payload["reports"][0]["report_id"] == "run-1:final"
    assert payload["reports"][0]["status"] == "final"
    assert payload["reports"][0]["title"] == "AI Policy Report"


def test_report_service_gets_report_by_id(tmp_path) -> None:
    _write_report_run(tmp_path, "run-1", "2026-05-11T00:00:00Z", "AI Policy Report")

    record = ReportApplicationService(artifact_root=tmp_path).get_report("run-1:final")

    assert record.report_id == "run-1:final"
    assert record.run_id == "run-1"
    assert record.status == "final"
    assert record.title == "AI Policy Report"
    assert record.report_json == {"title": "AI Policy Report"}


def test_report_service_lists_report_artifacts(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-1",
        "2026-05-11T00:00:00Z",
        "AI Policy Report",
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )

    result = ReportApplicationService(artifact_root=tmp_path).list_reports(
        workflow_id=LEGACY_DAILY_WORKFLOW_ID
    )

    payload = result.to_dict()
    assert payload["workflow_id"] == LEGACY_DAILY_WORKFLOW_ID
    assert payload["report_count"] == 1
    assert payload["reports"][0]["report_id"] == "run-1:final"


def test_report_service_lists_reports_by_daily_workflow_family(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-legacy",
        "2026-05-10T00:00:00Z",
        "Legacy Daily",
        workflow_id=LEGACY_DAILY_WORKFLOW_ID,
    )
    _write_report_run(
        tmp_path,
        "run-agentic",
        "2026-05-11T00:00:00Z",
        "Agentic Daily",
        workflow_id="daily-intelligence-agentic",
    )

    result = ReportApplicationService(artifact_root=tmp_path).list_reports(
        workflow_family="daily"
    )

    payload = result.to_dict()
    assert payload["workflow_family"] == "daily"
    assert payload["report_count"] == 2
    assert {report["workflow_id"] for report in payload["reports"]} == {
        LEGACY_DAILY_WORKFLOW_ID,
        "daily-intelligence-agentic",
    }



def test_report_service_quality_prefers_quality_trace_payload(tmp_path) -> None:
    _write_report_run(
        tmp_path,
        "run-blocked",
        "2026-05-11T00:00:00Z",
        "Blocked Daily",
        report_json={
            "title": "Blocked Daily",
            "quality_trace": {
                "decision": "blocked",
                "route": "human_review",
                "citation_failure_categories": [
                    {"code": "unsupported_claims", "count": 1, "items": ["Summary: Unsupported claim"]}
                ],
                "unsupported_sections": ["Summary"],
                "remediation": ["remove unsupported claim"],
            },
        },
    )

    result = ReportApplicationService(artifact_root=tmp_path).report_quality("run-blocked:final")

    assert result.to_dict()["quality"]["decision"] == "blocked"
    assert result.to_dict()["quality"]["route"] == "human_review"
    assert result.to_dict()["quality"]["unsupported_sections"] == ["Summary"]


def test_report_service_rejects_empty_query(tmp_path) -> None:
    service = ReportApplicationService(artifact_root=tmp_path)

    with pytest.raises(ValueError, match="query is required"):
        service.search_reports(query="")


def test_report_service_uses_postgres_when_database_dsn_is_configured(tmp_path) -> None:
    service = ReportApplicationService(
        artifact_root=tmp_path,
        env={"NEWS_DATABASE_DSN": "postgresql://example"},
    )

    assert service.repository.__class__.__name__ == "PostgresRepository"


def _write_report_run(
    root,
    run_id: str,
    finished_at: str,
    title: str,
    *,
    workflow_id: str | None = None,
    report_json: dict | None = None,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    payload = report_json or {"title": title}
    (run_dir / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "report.md").write_text(f"# {title}\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "status": "succeeded",
                "finished_at": finished_at,
                "quality_score": 0.9,
                "artifacts": {
                    "report_json": "report.json",
                    "report_markdown": "report.md",
                },
            }
        ),
        encoding="utf-8",
    )
