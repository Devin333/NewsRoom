import json

from fastapi.testclient import TestClient

from core.framework.workers import Task, TaskStatus
from interfaces.api import create_app
from interfaces.services.run_inspection_service import RunInspectionService
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
    assert response.headers["x-request-id"] == payload["request_id"]
    assert payload["schema_version"] == "1.0"


def test_api_uses_client_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": "client-req_1.2"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["request_id"] == "client-req_1.2"
    assert response.headers["x-request-id"] == "client-req_1.2"


def test_api_replaces_invalid_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": "../secret"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["request_id"].startswith("req_")
    assert payload["request_id"] != "../secret"
    assert response.headers["x-request-id"] == payload["request_id"]


def test_health_does_not_require_api_token_when_auth_enabled() -> None:
    client = TestClient(create_app(api_token="test-token"))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_api_token_auth_rejects_missing_token() -> None:
    client = TestClient(
        create_app(
            api_token="test-token",
            report_service_factory=lambda: _FakeReportService(),
        )
    )

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert payload["success"] is False
    assert payload["error"]["code"] == "unauthorized"
    assert "test-token" not in json.dumps(payload)


def test_api_token_auth_error_preserves_request_id_header() -> None:
    client = TestClient(create_app(api_token="test-token"))

    response = client.get("/api/v1/mcp/catalog", headers={"X-Request-ID": "auth-check"})
    payload = response.json()

    assert response.status_code == 401
    assert payload["request_id"] == "auth-check"
    assert response.headers["x-request-id"] == "auth-check"


def test_api_token_auth_rejects_invalid_token() -> None:
    client = TestClient(
        create_app(
            api_token="test-token",
            report_service_factory=lambda: _FakeReportService(),
        )
    )

    response = client.get("/api/v1/reports/latest", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_api_token_auth_allows_valid_bearer_token() -> None:
    client = TestClient(
        create_app(
            api_token="test-token",
            report_service_factory=lambda: _FakeReportService(),
        )
    )

    response = client.get("/api/v1/reports/latest", headers={"Authorization": "Bearer test-token"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["report_id"] == "report-1"


def test_api_validation_errors_use_common_envelope() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/runs/daily",
        json={"profile": "live-offline", "topic": "AI", "source_limit": 0},
        headers={"X-Request-ID": "invalid-run"},
    )
    payload = response.json()

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "invalid-run"
    assert payload["success"] is False
    assert payload["request_id"] == "invalid-run"
    assert payload["error"]["code"] == "invalid_request"
    assert payload["error"]["user_action_required"] is True
    errors = payload["error"]["details"]["errors"]
    assert errors[0]["loc"] == ["body", "source_limit"]
    assert errors[0]["type"]


def test_api_unknown_route_uses_common_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/not-a-route", headers={"X-Request-ID": "missing-route"})
    payload = response.json()

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "missing-route"
    assert payload["success"] is False
    assert payload["request_id"] == "missing-route"
    assert payload["error"]["code"] == "not_found"


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


def test_latest_report_preserves_missing_manifest_path() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _NullManifestReportService()))

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["manifest_path"] is None


def test_get_report_returns_report_detail() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports/report-1")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["report_id"] == "report-1"
    assert payload["data"]["run_id"] == "run-1"
    assert payload["data"]["title"] == "Daily Intelligence"


def test_list_reports_returns_report_catalog() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports?limit=1&workflow_id=daily-intelligence-live")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["workflow_id"] == "daily-intelligence-live"
    assert payload["data"]["report_count"] == 1
    assert payload["data"]["reports"][0]["report_id"] == "report-1"
    assert payload["data"]["reports"][0]["workflow_id"] == "daily-intelligence-live"


def test_latest_report_missing_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _MissingReportService()))

    response = client.get("/api/v1/reports/latest")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "report_not_found"
    assert payload["error"]["user_action_required"] is True


def test_get_report_missing_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _MissingReportService()))

    response = client.get("/api/v1/reports/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "report_not_found"
    assert payload["error"]["user_action_required"] is True


def test_get_report_invalid_id_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports/bad-id")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_report_id"


def test_report_search_returns_reports() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/search/reports?q=policy&limit=1")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["query"] == "policy"
    assert payload["data"]["report_count"] == 1
    assert payload["data"]["reports"][0]["report_id"] == "report-1"
    assert payload["data"]["reports"][0]["run_id"] == "run-1"


def test_report_search_invalid_query_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/search/reports?q=&limit=1")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_report_search"


def test_report_catalog_invalid_limit_uses_unified_error() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports?limit=0")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_report_catalog"


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


def test_source_arxiv_fetch_returns_items() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.post("/api/v1/sources/arxiv/fetch", json={"query": "cat:cs.AI", "limit": 1})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["source_type"] == "arxiv"
    assert payload["data"]["item_count"] == 1
    assert payload["data"]["items"][0]["title"] == "Agent Runtime Evaluation"


def test_source_github_releases_fetch_returns_items() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.post(
        "/api/v1/sources/github/releases",
        json={"repository": "owner/repo", "limit": 1},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["source_type"] == "github"
    assert payload["data"]["item_count"] == 1
    assert payload["data"]["items"][0]["title"] == "Version 1.0.0"


def test_source_preview_invalid_request_uses_unified_error() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.post("/api/v1/sources/github/releases", json={"repository": "bad", "limit": 0})
    payload = response.json()

    assert response.status_code == 422
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_request"


def test_entities_create_and_list_return_payloads() -> None:
    client = TestClient(create_app(entity_service_factory=lambda: _FakeEntityService()))

    create_response = client.post(
        "/api/v1/entities",
        json={"name": "OpenAI", "kind": "company", "aliases": ["ChatGPT"]},
    )
    list_response = client.get("/api/v1/entities?enabled_only=true&kind=company")

    create_payload = create_response.json()
    list_payload = list_response.json()

    assert create_response.status_code == 200
    assert create_payload["success"] is True
    assert create_payload["data"]["entity_id"] == "company:openai"
    assert list_response.status_code == 200
    assert list_payload["data"]["entity_count"] == 1
    assert list_payload["data"]["entities"][0]["aliases"] == ["ChatGPT"]


def test_entities_lifecycle_routes_return_payloads() -> None:
    client = TestClient(create_app(entity_service_factory=lambda: _FakeEntityService()))

    disable_response = client.post("/api/v1/entities/company:openai/disable")
    enable_response = client.post("/api/v1/entities/company:openai/enable")
    delete_response = client.delete("/api/v1/entities/company:openai")

    assert disable_response.status_code == 200
    assert disable_response.json()["data"]["enabled"] is False
    assert enable_response.status_code == 200
    assert enable_response.json()["data"]["enabled"] is True
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"entity_id": "company:openai", "deleted": True}


def test_entity_report_matches_return_matches() -> None:
    client = TestClient(create_app(entity_service_factory=lambda: _FakeEntityService()))

    response = client.get(
        "/api/v1/entities/company:openai/report-matches?limit=1&workflow_id=daily-intelligence-live"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["match_count"] == 1
    assert payload["data"]["matches"][0]["report_id"] == "run-1:final"
    assert payload["data"]["matches"][0]["matched_aliases"] == ["OpenAI", "ChatGPT"]


def test_entities_create_invalid_metadata_returns_domain_error() -> None:
    client = TestClient(create_app(entity_service_factory=lambda: _FakeEntityService()))

    response = client.post(
        "/api/v1/entities",
        json={"name": "OpenAI", "metadata": {"api_key": "hidden"}},
    )
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_entity_request"


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


def test_run_replay_returns_bundle() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/replay")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["run_id"] == "run-1"
    assert payload["data"]["artifact_count"] == 1


def test_run_replay_missing_uses_unified_error() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _MissingRunInspectionService()))

    response = client.get("/api/v1/runs/missing/replay")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "run_not_found"


def test_run_replay_invalid_uses_unified_error() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _InvalidReplayInspectionService()))

    response = client.get("/api/v1/runs/bad/replay")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_run_replay_request"


def test_run_replay_api_reads_real_files_and_redacts(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "status": "succeeded",
                "artifacts": {"events": "events.jsonl", "report_json": "report.json"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started", "payload": {"token": "hidden"}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Report", "api_key": "hidden"}),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(run_inspection_service_factory=lambda: RunInspectionService(tmp_path))
    )

    response = client.get("/api/v1/runs/run-1/replay")
    payload = response.json()
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["data"]["artifacts"]}

    assert response.status_code == 200
    assert payload["data"]["event_count"] == 1
    assert payload["data"]["events"][0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"]["content"]["api_key"] == "[redacted]"


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

    def get_report(self, report_id):
        if report_id != "report-1":
            raise ValueError(f"invalid report id: {report_id}")
        return self.latest_report()

    def list_reports(self, *, limit, workflow_id=None):
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        return _FakeResult(
            {
                "limit": limit,
                "workflow_id": workflow_id,
                "report_count": 1,
                "reports": [
                    {
                        "report_id": "report-1",
                        "run_id": "run-1",
                        "status": "final",
                        "finished_at": "2026-05-11T01:00:00Z",
                        "title": "Daily Intelligence",
                        "quality_score": 0.9,
                        "workflow_id": "daily-intelligence-live",
                        "manifest_path": ".newsroom/runs/run-1/manifest.json",
                        "report_json_path": ".newsroom/runs/run-1/report.json",
                        "report_markdown_path": ".newsroom/runs/run-1/report.md",
                    }
                ],
            }
        )

    def search_reports(self, *, query, limit):
        if not query:
            raise ValueError("query is required")
        return _FakeResult(
            {
                "query": query,
                "limit": limit,
                "report_count": 1,
                "reports": [
                    {
                        "report_id": "report-1",
                        "run_id": "run-1",
                        "status": "succeeded",
                        "finished_at": "2026-05-11T01:00:00Z",
                        "title": "Daily Intelligence",
                        "quality_score": 0.9,
                        "manifest_path": ".newsroom/runs/run-1/manifest.json",
                        "report_json_path": ".newsroom/runs/run-1/report.json",
                        "report_markdown_path": ".newsroom/runs/run-1/report.md",
                    }
                ],
            }
        )


class _MissingReportService:
    def latest_report(self):
        raise FileNotFoundError("no local report found")

    def get_report(self, report_id):
        raise FileNotFoundError(f"report not found: {report_id}")


class _NullManifestReportService:
    def latest_report(self):
        return ReportRecord(
            report_id="report-1",
            run_id="run-1",
            status="final",
            title="Daily Intelligence",
            report_json={"title": "Daily Intelligence"},
            report_markdown="# Daily Intelligence",
            quality_score=0.9,
            manifest_path=None,
        )


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

    def fetch_arxiv(self, *, query, limit):
        if not query:
            raise ValueError("query is required")
        return _FakeResult(
            {
                "source_id": "arxiv",
                "source_type": "arxiv",
                "query": query,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-arxiv",
                        "source_id": "arxiv",
                        "source_name": "arXiv",
                        "source_type": "arxiv",
                        "title": "Agent Runtime Evaluation",
                        "url": "https://arxiv.org/abs/2605.00001",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Paper summary",
                        "raw_content": None,
                        "authors": ["Alice Example"],
                        "tags": ["cs.AI"],
                        "language": "en",
                        "metadata": {"arxiv_id": "2605.00001v1"},
                    }
                ],
                "errors": [],
            }
        )

    def fetch_github_releases(self, *, repository, limit):
        if "/" not in repository:
            raise ValueError("github repository must use owner/repo format")
        return _FakeResult(
            {
                "source_id": "github",
                "source_type": "github",
                "query": repository,
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-github",
                        "source_id": "github",
                        "source_name": "GitHub",
                        "source_type": "github",
                        "title": "Version 1.0.0",
                        "url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Release notes",
                        "raw_content": None,
                        "authors": ["maintainer"],
                        "tags": ["v1.0.0"],
                        "language": "en",
                        "metadata": {"repository": "owner/repo"},
                    }
                ],
                "errors": [],
            }
        )


class _FakeEntityService:
    def create_entity(self, *, name, kind, aliases, entity_id, enabled, metadata):
        if "api_key" in metadata:
            raise ValueError("entity metadata contains secret-like key: api_key")
        return _FakeEntity(
            {
                "entity_id": entity_id or "company:openai",
                "name": name,
                "kind": kind,
                "aliases": aliases,
                "enabled": enabled,
                "metadata": metadata,
                "created_at": "2026-05-11T00:00:00Z",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        )

    def list_entities(self, *, enabled_only, kind):
        return _FakeResult(
            {
                "entity_count": 1,
                "entities": [
                    {
                        "entity_id": "company:openai",
                        "name": "OpenAI",
                        "kind": "company",
                        "aliases": ["ChatGPT"],
                        "enabled": True,
                        "metadata": {},
                        "created_at": "2026-05-11T00:00:00Z",
                        "updated_at": "2026-05-11T00:00:00Z",
                    }
                ],
            }
        )

    def set_enabled(self, entity_id, *, enabled):
        return _FakeEntity(
            {
                "entity_id": entity_id,
                "name": "OpenAI",
                "kind": "company",
                "aliases": ["ChatGPT"],
                "enabled": enabled,
                "metadata": {},
                "created_at": "2026-05-11T00:00:00Z",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        )

    def delete_entity(self, entity_id):
        return True

    def match_reports(self, entity_id, *, limit, workflow_id):
        return _FakeResult(
            {
                "entity": {
                    "entity_id": entity_id,
                    "name": "OpenAI",
                    "kind": "company",
                    "aliases": ["ChatGPT"],
                    "enabled": True,
                    "metadata": {},
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z",
                },
                "limit": limit,
                "workflow_id": workflow_id,
                "match_count": 1,
                "matches": [
                    {
                        "report_id": "run-1:final",
                        "run_id": "run-1",
                        "title": "Daily Intelligence: OpenAI",
                        "finished_at": "2026-05-11T00:00:00Z",
                        "workflow_id": "daily-intelligence-live",
                        "matched_aliases": ["OpenAI", "ChatGPT"],
                        "match_count": 2,
                        "quality_score": 0.9,
                    }
                ],
            }
        )


class _FakeEntity:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


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

    def replay_run(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "manifest": {"run_id": run_id, "status": "succeeded"},
                "manifest_path": f".newsroom/runs/{run_id}/manifest.json",
                "event_count": 1,
                "events": [{"event_type": "workflow_started", "payload": {}}],
                "events_path": f".newsroom/runs/{run_id}/events.jsonl",
                "events_error": None,
                "artifact_count": 1,
                "artifacts": [
                    {
                        "artifact_key": "report_json",
                        "relative_path": "report.json",
                        "content_type": "application/json",
                        "size_bytes": 14,
                        "content": {"title": "Report"},
                        "read_error": None,
                    }
                ],
            }
        )


class _MissingRunInspectionService:
    def get_run(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def replay_run(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def list_runs(self, *, limit):
        return _FakeResult({"run_count": 0, "runs": []})


class _InvalidReplayInspectionService:
    def replay_run(self, run_id):
        raise ValueError(f"invalid run id: {run_id}")


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
