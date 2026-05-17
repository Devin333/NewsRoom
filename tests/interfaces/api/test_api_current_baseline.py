from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from core.framework.workers import Task, TaskStatus
from interfaces.api import create_app
from interfaces.services.worker_service import EnqueuedTaskResult
from storage.repository import ReportRecord


def test_create_app_builds_current_fastapi_app() -> None:
    app = create_app(audit_emitter_factory=None)

    assert app.title == "NewsRoom API"


def test_current_core_api_routes_return_unified_envelope() -> None:
    client = TestClient(_baseline_app())

    cases = [
        ("GET", "/health", None),
        ("GET", "/health/live", None),
        ("GET", "/health/ready", None),
        ("GET", "/health/dependencies", None),
        (
            "POST",
            "/api/v1/runs",
            {
                "workflow_id": "daily",
                "profile": "live-offline",
                "topic": "AI",
                "source_limit": 3,
                "run_id": "baseline-run",
            },
        ),
        ("GET", "/api/v1/reports/latest", None),
        ("GET", "/api/v1/reports", None),
        (
            "POST",
            "/api/v1/memory/search",
            {
                "query": "OpenAI",
                "collection": "report_sections",
                "limit": 5,
            },
        ),
    ]

    for method, path, json_body in cases:
        response = client.request(method, path, json=json_body)
        payload = response.json()

        assert response.status_code == 200, path
        assert payload["success"] is True, path
        assert "request_id" in payload, path
        assert payload["schema_version"] == "1.0", path
        assert "data" in payload, path


def _baseline_app():
    return create_app(
        worker_service_factory=lambda: _FakeWorkerService(),
        report_service_factory=lambda: _FakeReportService(),
        memory_service_factory=lambda: _FakeMemoryService(),
        diagnostic_service_factory=lambda: _FakeDiagnosticService(),
        audit_emitter_factory=None,
    )


class _FakeWorkerService:
    def enqueue_daily(self, **kwargs: Any) -> EnqueuedTaskResult:
        task = Task(
            task_id="task-baseline",
            task_type="daily_intelligence.run",
            payload={
                "profile": kwargs["profile"],
                "topic": kwargs["topic"],
                "source_limit": kwargs["source_limit"],
                "run_id": kwargs["run_id"],
            },
            queue_name=kwargs["queue_name"],
        )
        task.status = TaskStatus.QUEUED
        return EnqueuedTaskResult(task=task, message_id="1-0")


class _FakeReportService:
    def latest_report(self) -> ReportRecord:
        return ReportRecord(
            report_id="report-baseline",
            run_id="run-baseline",
            status="final",
            title="Daily Intelligence",
            report_json={"title": "Daily Intelligence"},
            report_markdown="# Daily Intelligence",
            quality_score=0.95,
            manifest_path=".newsroom/runs/run-baseline/manifest.json",
        )

    def list_reports(self, *, limit: int, workflow_id: str | None = None) -> "_FakeResult":
        return _FakeResult(
            {
                "limit": limit,
                "workflow_id": workflow_id,
                "report_count": 1,
                "reports": [self.latest_report().to_dict()],
            }
        )


class _FakeMemoryService:
    def search(
        self,
        *,
        text: str,
        collection: str,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> "_FakeResult":
        return _FakeResult(
            {
                "collection": collection,
                "query": text,
                "filters": filters or {},
                "limit": limit,
                "result_count": 0,
                "results": [],
            }
        )


class _FakeDiagnosticService:
    def run(self) -> "_FakeResult":
        return _FakeResult(
            {
                "status": "ok",
                "summary": "baseline diagnostics",
                "checks": [],
            }
        )


class _FakeResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)
