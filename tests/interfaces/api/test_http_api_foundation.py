import hashlib
import json

from fastapi.testclient import TestClient

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from interfaces.api import create_app
from interfaces.api.app import _api_token_from_env
from interfaces.events import AuditEmitter, InMemoryAuditSink
from interfaces.services.run_inspection_service import RunInspectionService
from infrastructure.storage.persistence import ReportRecord
from tests.fixtures.workflow_runs import write_canonical_terminal_run


RESEARCH_WORKFLOW_ID = "research.paper_analysis"


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


def test_api_token_can_be_loaded_from_newsroom_env_alias() -> None:
    client = TestClient(
        create_app(
            api_token=_api_token_from_env({"NEWSROOM_API_TOKEN": "room-token"}),
            report_service_factory=lambda: _FakeReportService(),
        )
    )

    missing = client.get("/api/v1/reports/latest")
    valid = client.get("/api/v1/reports/latest", headers={"Authorization": "Bearer room-token"})

    assert missing.status_code == 401
    assert valid.status_code == 200


def test_api_key_readonly_role_allows_read_and_blocks_write() -> None:
    fake_research = _FakeResearchService()
    client = TestClient(
        create_app(
            api_keys={"read-token": "read-only"},
            report_service_factory=lambda: _FakeReportService(),
            research_service_factory=lambda: fake_research,
        )
    )

    read_response = client.get(
        "/api/v1/reports/latest",
        headers={"Authorization": "Bearer read-token"},
    )
    write_response = client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2401.00001"},
        headers={"Authorization": "Bearer read-token"},
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403
    assert write_response.json()["error"]["code"] == "forbidden"
    assert write_response.json()["error"]["details"]["required_permission"] == "write:runs"
    assert fake_research.analyze_calls == []


def test_api_key_operator_role_allows_run_write() -> None:
    fake_research = _FakeResearchService()
    client = TestClient(
        create_app(
            api_keys={"operator-token": ["operator"]},
            research_service_factory=lambda: fake_research,
        )
    )

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2401.00001",
            "runId": "rbac-run",
        },
        headers={"Authorization": "Bearer operator-token"},
    )

    assert response.status_code == 200
    assert fake_research.analyze_calls[0].run_id == "rbac-run"


def test_api_key_mcp_client_role_allows_mcp_catalog_only() -> None:
    fake_research = _FakeResearchService()
    client = TestClient(
        create_app(
            api_keys={"mcp-token": "mcp_client"},
            research_service_factory=lambda: fake_research,
        )
    )

    catalog = client.get(
        "/api/v1/mcp/catalog",
        headers={"Authorization": "Bearer mcp-token", "X-API-Client-ID": "mcp-client-1"},
    )
    run = client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2401.00001"},
        headers={"Authorization": "Bearer mcp-token", "X-API-Client-ID": "mcp-client-1"},
    )

    assert catalog.status_code == 200
    assert run.status_code == 403
    assert run.json()["error"]["details"]["required_permission"] == "write:runs"


def test_api_key_roles_can_be_loaded_from_env(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEYS", "env-read=read-only")
    client = TestClient(
        create_app(
            report_service_factory=lambda: _FakeReportService(),
        )
    )

    response = client.get(
        "/api/v1/reports/latest",
        headers={"Authorization": "Bearer env-read"},
    )

    assert response.status_code == 200


def test_api_key_role_lists_can_be_loaded_from_json_env(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEYS", json.dumps({"env-operator": ["operator"]}))
    fake_research = _FakeResearchService()
    client = TestClient(create_app(research_service_factory=lambda: fake_research))

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2401.00001",
            "runId": "env-rbac-run",
        },
        headers={"Authorization": "Bearer env-operator"},
    )

    assert response.status_code == 200
    assert fake_research.analyze_calls[0].run_id == "env-rbac-run"


def test_api_key_fingerprint_is_used_for_audit_records() -> None:
    sink = InMemoryAuditSink()
    client = TestClient(
        create_app(
            api_keys={"read-token": "read-only"},
            report_service_factory=lambda: _FakeReportService(),
            audit_emitter_factory=lambda: AuditEmitter(sink),
        )
    )

    response = client.get(
        "/api/v1/reports/latest",
        headers={
            "Authorization": "Bearer read-token",
            "X-API-Client-ID": "readonly-client",
        },
    )

    assert response.status_code == 200
    fingerprint = hashlib.sha256(b"read-token").hexdigest()
    assert sink.records[0].actor.actor_id == f"api-key:{fingerprint}"
    assert sink.records[0].actor.roles == ["read-only"]


def test_api_validation_errors_use_common_envelope() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={"sourceUrl": "https://arxiv.org/abs/2401.00001"},
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
    assert errors[0]["loc"] == ["body", "paperId"]
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


def test_submit_research_analysis_uses_research_service() -> None:
    fake_research = _FakeResearchService()
    client = TestClient(create_app(research_service_factory=lambda: fake_research))

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2401.00001",
            "runId": "api-run",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert fake_research.analyze_calls[0].paper_id == "paper-1"
    assert payload["success"] is True
    assert payload["data"]["status"] == "succeeded"
    assert payload["data"]["runId"] == "api-run"
    assert payload["data"]["paperId"] == "paper-1"


def test_submit_research_analysis_accepts_options() -> None:
    fake_research = _FakeResearchService()
    client = TestClient(create_app(research_service_factory=lambda: fake_research))

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2401.00001",
            "runId": "api-options-run",
            "options": {"max_turns": 4},
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert fake_research.analyze_calls[0].options == {"max_turns": 4}
    assert payload["success"] is True
    assert payload["data"]["status"] == "queued"
    assert payload["data"]["runId"] == "api-options-run"


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

    response = client.get(f"/api/v1/reports?limit=1&workflow_id={RESEARCH_WORKFLOW_ID}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["workflow_id"] == RESEARCH_WORKFLOW_ID
    assert payload["data"]["report_count"] == 1
    assert payload["data"]["reports"][0]["report_id"] == "report-1"
    assert payload["data"]["reports"][0]["workflow_id"] == RESEARCH_WORKFLOW_ID


def test_list_reports_returns_report_catalog_for_research_workflow_family() -> None:
    client = TestClient(create_app(report_service_factory=lambda: _FakeReportService()))

    response = client.get("/api/v1/reports?limit=1&workflow_family=research")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["workflow_family"] == "research"
    assert payload["data"]["report_count"] == 1


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
    assert payload["data"]["counts"]["claims"] == 2
    assert payload["data"]["metadata"]["claim_consolidation"]["merged"] == 1
    assert payload["data"]["ingestion"]["documents_indexed"] == 3


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


def test_sources_validation_returns_registry_validation() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.get("/api/v1/sources/validation")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["is_valid"] is True
    assert payload["data"]["error_count"] == 0


def test_sources_categories_and_priorities_return_catalogs() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    categories_response = client.get("/api/v1/sources/categories")
    priorities_response = client.get("/api/v1/sources/priorities")

    assert categories_response.status_code == 200
    assert categories_response.json()["data"]["categories"] == ["research"]
    assert priorities_response.status_code == 200
    assert priorities_response.json()["data"]["priorities"] == ["p0"]


def test_source_fetch_returns_configured_source_items() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    response = client.post("/api/v1/sources/fetch", json={"source_id": "source-1", "limit": 1, "force": True})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["source_id"] == "source-1"
    assert payload["data"]["items"][0]["title"] == "Source item"


def test_source_batch_fetch_routes_return_payloads() -> None:
    client = TestClient(create_app(source_service_factory=lambda: _FakeSourceService()))

    category_response = client.post("/api/v1/sources/fetch-category", json={"category": "research", "limit_per_source": 1})
    priority_response = client.post("/api/v1/sources/fetch-priority", json={"priority": "p0", "limit_per_source": 1})
    topic_response = client.post("/api/v1/sources/fetch-topic", json={"topic": "AI agents", "limit_per_source": 1})

    assert category_response.status_code == 200
    assert category_response.json()["data"]["source_count"] == 1
    assert priority_response.status_code == 200
    assert priority_response.json()["data"]["source_count"] == 1
    assert topic_response.status_code == 200
    assert topic_response.json()["data"]["selection_report"]["topic"] == "AI agents"


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
        f"/api/v1/entities/company:openai/report-matches?limit=1&workflow_id={RESEARCH_WORKFLOW_ID}"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["match_count"] == 1
    assert payload["data"]["matches"][0]["report_id"] == "run-1:final"
    assert payload["data"]["matches"][0]["matched_aliases"] == ["OpenAI", "ChatGPT"]


def test_entity_report_matches_accepts_workflow_family() -> None:
    client = TestClient(create_app(entity_service_factory=lambda: _FakeEntityService()))

    response = client.get(
        "/api/v1/entities/company:openai/report-matches?limit=1&workflow_family=daily"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["workflow_family"] == "daily"
    assert payload["data"]["match_count"] == 1



    response = client.post(
        "/api/v1/entities",
        json={"name": "OpenAI", "metadata": {"api_key": "hidden"}},
    )
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_entity_request"


def test_subscriptions_create_and_list_return_payloads() -> None:
    client = TestClient(create_app(subscription_service_factory=lambda: _FakeSubscriptionService()))

    create_response = client.post(
        "/api/v1/subscriptions",
        json={"topic": "AI policy", "subscription_id": "weekly:ai-policy", "source_limit": 3},
    )
    list_response = client.get("/api/v1/subscriptions?enabled_only=true&cadence=weekly")

    create_payload = create_response.json()
    list_payload = list_response.json()

    assert create_response.status_code == 200
    assert create_payload["success"] is True
    assert create_payload["data"]["subscription_id"] == "weekly:ai-policy"
    assert list_response.status_code == 200
    assert list_payload["data"]["subscription_count"] == 1
    assert list_payload["data"]["subscriptions"][0]["topic"] == "AI policy"


def test_subscriptions_lifecycle_routes_return_payloads() -> None:
    client = TestClient(create_app(subscription_service_factory=lambda: _FakeSubscriptionService()))

    disable_response = client.post("/api/v1/subscriptions/weekly:ai-policy/disable")
    enable_response = client.post("/api/v1/subscriptions/weekly:ai-policy/enable")
    delete_response = client.delete("/api/v1/subscriptions/weekly:ai-policy")

    assert disable_response.status_code == 200
    assert disable_response.json()["data"]["enabled"] is False
    assert enable_response.status_code == 200
    assert enable_response.json()["data"]["enabled"] is True
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {
        "subscription_id": "weekly:ai-policy",
        "deleted": True,
    }


def test_subscriptions_create_invalid_metadata_returns_domain_error() -> None:
    client = TestClient(create_app(subscription_service_factory=lambda: _FakeSubscriptionService()))

    response = client.post(
        "/api/v1/subscriptions",
        json={"topic": "AI policy", "metadata": {"api_key": "hidden"}},
    )
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_subscription_request"


def test_mcp_catalog_returns_catalog() -> None:
    client = TestClient(create_app(mcp_service_factory=lambda: _FakeMCPService()))

    response = client.get("/api/v1/mcp/catalog")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["tools"][0]["name"] == "news.source.health"


def test_mcp_capabilities_returns_manifest() -> None:
    client = TestClient(create_app(mcp_service_factory=lambda: _FakeMCPService()))

    response = client.get("/api/v1/mcp/capabilities")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["schema_version"] == "newsroom.mcp_capability_manifest.v1"
    assert payload["data"]["boundary"] == "inbound_mcp_server"
    assert payload["data"]["version"] == "1.0"
    assert payload["data"]["capabilities"][0]["name"] == "news.source.health"
    assert payload["data"]["capabilities"][0]["permission"] == "sources:read"
    assert payload["data"]["capabilities"][0]["category"] == "sources"


def test_runs_list_returns_runs() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["run_count"] == 1
    assert payload["data"]["runs"][0]["run_id"] == "run-1"


def test_run_catalog_health_returns_health() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/catalog/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["health"]["severity"] == "ok"


def test_run_compare_returns_comparison() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/compare?base_run_id=run-1&target_run_id=run-2")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["comparison"]["same_workflow"] is True


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


def test_run_progress_streams_redacted_sse_frames() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/progress")
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.progress\n" in body
    assert "event: run.progress.done\n" in body
    assert '"run_id": "run-1"' in body
    assert "[redacted]" in body
    assert "hidden-token" not in body


def test_run_events_stream_uses_event_types_and_done_frame() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/events/stream?limit=1")
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: workflow_started\n" in body
    assert "event: run.events.done\n" in body
    assert '"sequence": null' in body
    assert '"event_count": 1' in body
    assert "[redacted]" in body
    assert "hidden-token" not in body


def test_run_progress_invalid_limit_uses_unified_error() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/progress?limit=0")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_run_progress_request"


def test_run_progress_missing_events_uses_unified_error() -> None:
    client = TestClient(
        create_app(run_inspection_service_factory=lambda: _MissingRunInspectionService())
    )

    response = client.get("/api/v1/runs/missing/progress")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "run_progress_not_found"


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


def test_run_replay_integrity_errors_use_stable_http_contracts() -> None:
    cases = [
        (ArtifactChecksumMismatchError, 409, "artifact_checksum_mismatch"),
        (ArtifactStoreMetadataError, 409, "artifact_metadata_corrupt"),
        (ArtifactStoreRequiredError, 500, "artifact_store_unavailable"),
    ]

    for error_type, expected_status, expected_code in cases:
        service = _FailingRunReplayService(error_type("run replay verification failed"))
        client = TestClient(
            create_app(run_inspection_service_factory=lambda service=service: service)
        )

        response = client.get("/api/v1/runs/run-1/replay")
        payload = response.json()

        assert response.status_code == expected_status
        assert payload["success"] is False
        assert payload["data"] is None
        assert payload["error"]["code"] == expected_code


def test_run_diagnostics_returns_diagnostics() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/diagnostics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["diagnostics"]["healthy"] is True


def test_run_health_returns_health() -> None:
    client = TestClient(create_app(run_inspection_service_factory=lambda: _FakeRunInspectionService()))

    response = client.get("/api/v1/runs/run-1/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["health"]["severity"] == "ok"


def test_run_replay_api_reads_real_files_and_redacts(tmp_path) -> None:
    write_canonical_terminal_run(
        tmp_path,
        events=[
            {
                "event_type": "workflow_started",
                "run_id": "run-1",
                "occurred_at": "2026-05-14T01:00:00Z",
                "payload": {"token": "hidden"},
            }
        ],
        extra_artifacts={
            "report_json": (
                "report.json",
                json.dumps({"title": "Report", "api_key": "hidden"}).encode("utf-8"),
            )
        },
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


def test_artifact_detail_integrity_errors_use_stable_http_contracts() -> None:
    cases = [
        (ArtifactChecksumMismatchError, 409, "artifact_checksum_mismatch"),
        (ArtifactStoreMetadataError, 409, "artifact_metadata_corrupt"),
        (ArtifactStoreRequiredError, 500, "artifact_store_unavailable"),
    ]

    for error_type, expected_status, expected_code in cases:
        service = _FailingArtifactService(error_type("artifact verification failed"))
        client = TestClient(create_app(artifact_service_factory=lambda service=service: service))

        responses = [
            client.get("/api/v1/runs/run-1/artifacts/output"),
            client.get("/api/v1/artifacts/output?run_id=run-1"),
        ]

        for response in responses:
            payload = response.json()
            assert response.status_code == expected_status
            assert payload["success"] is False
            assert payload["data"] is None
            assert payload["error"]["code"] == expected_code


class _FakeResearchService:
    def __init__(self) -> None:
        self.analyze_calls = []

    def analyze_paper(self, request):
        self.analyze_calls.append(request)
        status = "queued" if request.options else "succeeded"
        return {
            "runId": request.run_id or "research-run-1",
            "paperId": request.paper_id,
            "status": status,
            "analysisRef": f"artifact://{request.run_id or 'research-run-1'}/analysis",
        }


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

    def list_reports(self, *, limit, workflow_id=None, workflow_family=None):
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        return _FakeResult(
            {
                "limit": limit,
                "workflow_id": workflow_id,
                "workflow_family": workflow_family,
                "report_count": 1,
                "reports": [
                    {
                        "report_id": "report-1",
                        "run_id": "run-1",
                        "status": "final",
                        "finished_at": "2026-05-11T01:00:00Z",
                        "title": "Daily Intelligence",
                        "quality_score": 0.9,
                        "workflow_id": RESEARCH_WORKFLOW_ID,
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
                "counts": {"evidence": 1, "claims": 2, "entities": 1, "events": 1, "decisions": 0, "preferences": 0},
                "metadata": {"claim_consolidation": {"merged": 1}},
                "ingestion": {
                    "documents_indexed": 3,
                    "indexed_documents": 3,
                    "counts": {"claims": 2},
                    "metadata": {"claim_consolidation": {"merged": 1}},
                },
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

    def validate_sources(self):
        return _FakeResult(
            {
                "is_valid": True,
                "error_count": 0,
                "warning_count": 0,
                "issues": [],
            }
        )

    def source_categories(self):
        return {"categories": ["research"], "category_count": 1}

    def source_priorities(self):
        return {"priorities": ["p0"], "priority_count": 1}

    def fetch_source(self, *, source_id, limit, query=None, force=False):
        return _FakeResult(
            {
                "source_id": source_id,
                "source_type": "rss",
                "query": query or "",
                "item_count": 1,
                "error_count": 0,
                "items": [
                    {
                        "source_item_id": "raw-source",
                        "source_id": source_id,
                        "source_name": "Source",
                        "source_type": "rss",
                        "title": "Source item",
                        "url": "https://example.com/item",
                        "fetched_at": "2026-05-11T00:00:00Z",
                        "published_at": "2026-05-10T00:00:00Z",
                        "summary": "Source summary",
                        "raw_content": None,
                        "authors": [],
                        "tags": [],
                        "language": "en",
                        "metadata": {},
                    }
                ],
                "errors": [],
            }
        )

    def fetch_category(
        self,
        *,
        category,
        limit_per_source,
        enabled_only=True,
        priority=None,
        language=None,
        region=None,
        force=False,
    ):
        return _FakeResult(
            {
                "ok": True,
                "source_count": 1,
                "item_count": 1,
                "error_count": 0,
                "skipped_count": 0,
                "results": [],
            }
        )

    def fetch_priority(self, *, priority, limit_per_source, enabled_only=True, force=False):
        return _FakeResult(
            {
                "ok": True,
                "source_count": 1,
                "item_count": 1,
                "error_count": 0,
                "skipped_count": 0,
                "results": [],
            }
        )

    def fetch_topic_sources(
        self,
        *,
        topic,
        limit_per_source,
        enabled_only=True,
        category=None,
        priority=None,
        language=None,
        region=None,
        force=False,
    ):
        return _FakeResult(
            {
                "ok": True,
                "source_count": 1,
                "item_count": 1,
                "error_count": 0,
                "skipped_count": 0,
                "results": [],
                "selection_report": {"topic": topic},
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

    def match_reports(self, entity_id, *, limit, workflow_id=None, workflow_family=None):
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
                "workflow_family": workflow_family,
                "match_count": 1,
                "matches": [
                    {
                        "report_id": "run-1:final",
                        "run_id": "run-1",
                        "title": "Daily Intelligence: OpenAI",
                        "finished_at": "2026-05-11T00:00:00Z",
                        "workflow_id": RESEARCH_WORKFLOW_ID,
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


class _FakeSubscriptionService:
    def create_topic_subscription(
        self,
        *,
        topic,
        cadence,
        profile,
        source_limit,
        subscription_id,
        enabled,
        metadata,
    ):
        if "api_key" in metadata:
            raise ValueError("subscription metadata contains secret-like key: api_key")
        return _FakeSubscription(
            {
                "subscription_id": subscription_id or "weekly:ai-policy",
                "topic": topic,
                "cadence": cadence,
                "profile": profile,
                "source_limit": source_limit,
                "enabled": enabled,
                "metadata": metadata,
                "created_at": "2026-05-11T00:00:00Z",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        )

    def list_topic_subscriptions(self, *, enabled_only, cadence):
        return _FakeResult(
            {
                "subscription_count": 1,
                "subscriptions": [
                    {
                        "subscription_id": "weekly:ai-policy",
                        "topic": "AI policy",
                        "cadence": "weekly",
                        "profile": "live-offline",
                        "source_limit": 3,
                        "enabled": True,
                        "metadata": {},
                        "created_at": "2026-05-11T00:00:00Z",
                        "updated_at": "2026-05-11T00:00:00Z",
                    }
                ],
            }
        )

    def set_enabled(self, subscription_id, *, enabled):
        return _FakeSubscription(
            {
                "subscription_id": subscription_id,
                "topic": "AI policy",
                "cadence": "weekly",
                "profile": "live-offline",
                "source_limit": 3,
                "enabled": enabled,
                "metadata": {},
                "created_at": "2026-05-11T00:00:00Z",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        )

    def delete_topic_subscription(self, subscription_id):
        return True


class _FakeSubscription:
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

    def capability_manifest(self):
        return _FakeResult(
            {
                "version": "1.0",
                "server_name": "NewsRoom",
                "transport": "stdio/http",
                "auth_required": True,
                "default_permission": "mcp:read",
                "schema_version": "newsroom.mcp_capability_manifest.v1",
                "boundary": "inbound_mcp_server",
                "capability_count": 1,
                "capabilities": [
                    {
                        "name": "news.source.health",
                        "kind": "tool",
                        "title": "Read source health",
                        "description": "Read source health.",
                        "permission": "sources:read",
                        "read_only": True,
                        "category": "sources",
                        "boundary": "inbound_mcp_server",
                        "risk_level": "low",
                        "requires_approval": False,
                        "uri_template": None,
                        "input_schema": {},
                        "output_mime_type": None,
                        "metadata": {},
                    }
                ],
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
                "payload": {"profile": "live-offline", "token": "hidden-token"},
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

    def get_run_diagnostics(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "diagnostics": {
                    "healthy": True,
                    "health_report": {"severity": "ok"},
                    "timeline_summary": {"event_count": 2},
                },
            }
        )

    def get_run_health(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "health": {"severity": "ok", "healthy": True},
            }
        )

    def get_catalog_health(self):
        return _FakeResult(
            {
                "health": {
                    "severity": "ok",
                    "run_count": 1,
                    "latest_run_id": "run-1",
                }
            }
        )

    def compare_runs(self, base_run_id, target_run_id):
        return _FakeResult(
            {
                "base_run_id": base_run_id,
                "target_run_id": target_run_id,
                "comparison": {
                    "same_workflow": True,
                    "status_changed": False,
                    "has_behavioral_change": False,
                },
            }
        )


class _MissingRunInspectionService:
    def get_run(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def replay_run(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def get_run_diagnostics(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def get_run_health(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")

    def compare_runs(self, base_run_id, target_run_id):
        raise FileNotFoundError(f"run not found: {base_run_id}")

    def list_runs(self, *, limit):
        return _FakeResult({"run_count": 0, "runs": []})

    def get_catalog_health(self):
        return _FakeResult({"health": {"severity": "unknown", "run_count": 0}})


class _InvalidReplayInspectionService:
    def replay_run(self, run_id):
        raise ValueError(f"invalid run id: {run_id}")


class _FailingRunReplayService:
    def __init__(self, error) -> None:
        self.error = error

    def replay_run(self, run_id):
        raise self.error


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


class _FailingArtifactService:
    def __init__(self, error) -> None:
        self.error = error

    def get_artifact(self, run_id, artifact_key):
        raise self.error
