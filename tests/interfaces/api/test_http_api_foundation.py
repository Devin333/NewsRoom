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


def test_memory_reindex_returns_result() -> None:
    fake_memory = _FakeMemoryService()
    client = TestClient(create_app(memory_service_factory=lambda: fake_memory))

    response = client.post(
        "/api/v1/memory/reindex",
        json={"run_id": "run-1", "topic": "AI policy"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert fake_memory.reindex_calls == [{"run_id": "run-1", "topic": "AI policy"}]
    assert payload["success"] is True
    assert payload["data"]["run_id"] == "run-1"
    assert payload["data"]["documents_indexed"] == 3


def test_memory_reindex_missing_run_uses_unified_error() -> None:
    client = TestClient(create_app(memory_service_factory=lambda: _FakeMemoryService()))

    response = client.post("/api/v1/memory/reindex", json={"run_id": "missing"})
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "memory_reindex_source_not_found"


def test_admin_diagnose_returns_result() -> None:
    client = TestClient(create_app(diagnostic_service_factory=lambda: _FakeDiagnosticService()))

    response = client.get("/api/v1/admin/diagnose")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "warning"
    assert payload["data"]["checks"][0]["check_id"] == "redis"


def test_sources_list_returns_sources() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.get("/api/v1/sources")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["source_count"] == 1
    assert payload["data"]["sources"][0]["source_id"] == "source-1"


def test_sources_health_returns_health() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.get("/api/v1/sources/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["health"][0]["status"] == "healthy"


def test_mcp_catalog_returns_catalog() -> None:
    client = TestClient(create_app(mcp_service_factory=lambda: _FakeMCPService()))

    response = client.get("/api/v1/mcp/catalog")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["tools"][0]["name"] == "news.source.health"


def test_runs_list_returns_runs() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["run_count"] == 1
    assert payload["data"]["runs"][0]["run_id"] == "run-1"


def test_run_detail_missing_uses_unified_error() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _MissingRunInspectionService()))

    response = client.get("/api/v1/runs/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "run_not_found"


def test_run_events_returns_events() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/events?limit=1")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["event_count"] == 1
    assert payload["data"]["events"][0]["event_type"] == "workflow_started"


def test_run_events_invalid_limit_uses_unified_error() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/events?limit=0")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_run_events_request"


def test_artifact_list_returns_artifacts() -> None:
    client = TestClient(create_app(artifact_service_factory=lambda: _FakeArtifactService()))

    response = client.get("/api/v1/runs/run-1/artifacts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["artifact_count"] == 1
    assert payload["data"]["artifacts"][0]["artifact_key"] == "output"


def test_artifact_missing_uses_unified_error() -> None:
    client = TestClient(create_app(artifact_service_factory=lambda: _MissingArtifactService()))

    response = client.get("/api/v1/runs/run-1/artifacts/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "artifact_not_found"


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
    def __init__(self) -> None:
        self.reindex_calls = []

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

    def reindex_run(self, run_id, *, topic=None):
        if run_id == "missing":
            raise FileNotFoundError("run not found: missing")
        self.reindex_calls.append({"run_id": run_id, "topic": topic})
        return _FakeMemoryResult(
            {
                "run_id": run_id,
                "topic": topic,
                "documents_indexed": 3,
                "collections": ["evidence_items", "report_sections"],
                "document_ids": [
                    "run-1:report_section:0",
                    "run-1:report_section:1",
                    "run-1:evidence:ev-1",
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


class _FakeSourceService:
    def list_sources(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "sources": [
                    {
                        "source_id": "source-1",
                        "name": "Source",
                        "source_type": "rss",
                        "url": "https://example.com/rss",
                        "reliability": "high",
                        "authority_score": 0.9,
                        "enabled": True,
                        "topics": ["AI"],
                        "language": None,
                        "region": None,
                    }
                ],
            }
        )

    def source_health(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "health": [
                    {
                        "source_id": "source-1",
                        "status": "healthy",
                        "consecutive_failures": 0,
                        "last_success_at": None,
                        "last_failure_at": None,
                        "cooldown_until": None,
                        "last_error": None,
                    }
                ],
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeMCPService:
    def catalog(self):
        return _FakeResult(
            {
                "tools": [
                    {
                        "name": "news.source.health",
                        "title": "Read source health",
                        "description": "Read source health.",
                        "input_schema": {},
                    }
                ],
                "resources": [],
                "prompts": [],
            }
        )


class _FakeRunInspectionService:
    def list_runs(self, *, limit):
        return _FakeResult(
            {
                "run_count": 1,
                "runs": [
                    {
                        "run_id": "run-1",
                        "status": "succeeded",
                        "workflow_id": "daily",
                        "workflow_version": "0.1.0",
                        "profile": "live-offline",
                        "started_at": "2026-05-11T01:00:00Z",
                        "finished_at": None,
                        "quality_score": 1.0,
                        "step_count": 7,
                        "event_count": 16,
                        "manifest_path": ".newsroom/runs/run-1/manifest.json",
                    }
                ],
            }
        )

    def get_run(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "manifest": {"run_id": run_id, "status": "succeeded"},
                "manifest_path": f".newsroom/runs/{run_id}/manifest.json",
            }
        )

    def get_run_events(self, run_id, *, limit=None):
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        events = [
            {
                "event_type": "workflow_started",
                "occurred_at": "2026-05-11T01:00:00Z",
                "payload": {"profile": "live-offline"},
            },
            {
                "event_type": "workflow_succeeded",
                "occurred_at": "2026-05-11T01:00:01Z",
                "payload": {},
            },
        ]
        if limit is not None:
            events = events[:limit]
        return _FakeResult(
            {
                "run_id": run_id,
                "event_count": len(events),
                "events": events,
                "events_path": f".newsroom/runs/{run_id}/events.jsonl",
            }
        )


class _MissingRunInspectionService:
    def get_run(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def list_runs(self, *, limit):
        return _FakeResult({"run_count": 0, "runs": []})


class _FakeArtifactService:
    def list_artifacts(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_count": 1,
                "artifacts": [
                    {
                        "artifact_key": "output",
                        "relative_path": "output.json",
                        "content_type": "application/json",
                        "size_bytes": 14,
                    }
                ],
            }
        )

    def get_artifact(self, run_id, artifact_key):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_key": artifact_key,
                "relative_path": "output.json",
                "content_type": "application/json",
                "size_bytes": 14,
                "content": {"status": "ok"},
            }
        )


class _MissingArtifactService:
    def list_artifacts(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def get_artifact(self, run_id, artifact_key):
        raise FileNotFoundError(f"artifact not found: {artifact_key}")
