from fastapi.testclient import TestClient

from core.framework.workers import Task, TaskStatus
from interfaces.api import create_app
from interfaces.services.worker_service import EnqueuedTaskResult
from storage.repository import ReportRecord


def test_health_uses_common_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "ok"
    assert payload["request_id"].startswith("req_")
    assert payload["schema_version"] == "1.0"


def test_submit_daily_run_enqueues_task() -> None:
    fake_worker = _FakeWorkerService()
    client = TestClient(create_app(worker_service_factory=lambda: fake_worker))

    response = client.post(
        "/api/v1/runs/daily",
        json={
            "profile": "live-offline",
            "topic": "AI policy",
            "source_limit": 2,
            "run_id": "api-run",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert fake_worker.enqueue_calls[0]["topic"] == "AI policy"
    assert payload["success"] is True
    assert payload["data"]["status"] == "queued"
    assert payload["data"]["task_status"] == "queued"
    assert payload["data"]["task_id"] == "task-1"
    assert payload["data"]["run_id"] == "api-run"


def test_latest_report_returns_report_detail() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["report_id"] == "report-1"
    assert payload["data"]["run_id"] == "run-1"
    assert payload["data"]["title"] == "Daily Intelligence"


def test_latest_report_missing_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _MissingReportService()))

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "report_not_found"
    assert payload["error"]["user_action_required"] is True


def test_memory_search_returns_results() -> None:
    client = TestClient(create_app(memory_service_factory=lambda: _FakeMemoryService()))

    response = client.post(
        "/api/v1/memory/search",
        json={
            "query": "agent runtime",
            "collection": "report_sections",
            "limit": 2,
            "filters": {"topic": "AI"},
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["collection"] == "report_sections"
    assert payload["data"]["filters"] == {"topic": "AI"}
    assert payload["data"]["results"][0]["document_id"] == "doc-1"


def test_admin_diagnose_returns_result() -> None:
    client = TestClient(create_app(diagnostic_service_factory=lambda: _FakeDiagnosticService()))

    response = client.get("/api/v1/admin/diagnose")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "warning"
    assert payload["data"]["checks"][0]["check_id"] == "redis"


class _FakeWorkerService:
    def __init__(self) -> None:
        self.enqueue_calls = []

    def enqueue_daily(self, **kwargs):
        self.enqueue_calls.append(kwargs)
        task = Task(
            task_id="task-1",
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
    def latest_report(self):
        return ReportRecord(
            report_id="report-1",
            run_id="run-1",
            status="final",
            title="Daily Intelligence",
            report_json={"title": "Daily Intelligence"},
            report_markdown="# Daily Intelligence",
            quality_score=0.9,
            manifest_path=".newsroom/runs/run-1/manifest.json",
        )


class _MissingReportService:
    def latest_report(self):
        raise FileNotFoundError("no local report found")


class _FakeMemoryService:
    def search(self, **kwargs):
        return _FakeMemoryResult(
            {
                "collection": kwargs["collection"],
                "query": kwargs["text"],
                "filters": kwargs["filters"],
                "limit": kwargs["limit"],
                "result_count": 1,
                "results": [
                    {
                        "document_id": "doc-1",
                        "score": 0.9,
                        "text": "Agent runtime memory",
                        "source_type": "report_section",
                        "payload": {"topic": "AI"},
                        "run_id": None,
                        "report_id": None,
                        "evidence_id": None,
                        "source_item_id": None,
                    }
                ],
            }
        )


class _FakeMemoryResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeDiagnosticService:
    def run(self):
        return _FakeDiagnosticResult()


class _FakeDiagnosticResult:
    def to_dict(self):
        return {
            "status": "warning",
            "summary": "1 ok, 1 warning, 0 error, 0 skipped",
            "checks": [
                {
                    "check_id": "redis",
                    "name": "Redis",
                    "status": "ok",
                    "message": "ok",
                    "details": {},
                    "remediation": None,
                }
            ],
        }
