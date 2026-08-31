from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app


class _CatalogService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def parse_paper(self, command):
        self.calls.append(("parse_paper", (command,), {}))
        return {
            "runId": command.run_id or "parse-run",
            "paperId": "paper-1",
            "status": "parsed",
            "provenance": {"sourceSnapshotRefs": ["snapshot-1"]},
            "artifactRefs": ["artifact://research/document/hash"],
        }

    def get_sources(self, paper_id, *, actor):
        self.calls.append(("get_sources", (paper_id,), {"actor": actor}))
        return {"paperId": paper_id, "sources": [], "provenance": {}}

    def get_document(self, paper_id, *, actor):
        self.calls.append(("get_document", (paper_id,), {"actor": actor}))
        return {"paperId": paper_id, "document": None, "provenance": {}}

    def get_catalog(self, paper_id, *, actor):
        self.calls.append(("get_catalog", (paper_id,), {"actor": actor}))
        return {"paperId": paper_id, "catalog": {}, "provenance": {}}

    def get_code(self, paper_id, *, actor):
        self.calls.append(("get_code", (paper_id,), {"actor": actor}))
        return {"paperId": paper_id, "repositories": [], "provenance": {}}

    def get_benchmarks(self, paper_id, **kwargs):
        self.calls.append(("get_benchmarks", (paper_id,), kwargs))
        return {"paperId": paper_id, "scores": [], "relations": [], "provenance": {}}

    def list_catalog_papers(self, **kwargs):
        self.calls.append(("list_catalog_papers", (), kwargs))
        return {"papers": [], "query": kwargs["query"], "provenance": {}}

    def get_leaderboards(self, **kwargs):
        self.calls.append(("get_leaderboards", (), kwargs))
        return {"leaderboards": [], "provenance": {}}

    def refresh_catalog(self, paper_id=None, *, actor):
        self.calls.append(("refresh_catalog", (paper_id,), {"actor": actor}))
        return {"status": "catalog_ready", "refreshed": True, "provenance": {}}


def _client(service: _CatalogService) -> TestClient:
    return TestClient(
        create_app(
            research_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )


def test_research_catalog_routes_use_application_service_and_shared_envelope() -> None:
    service = _CatalogService()
    client = _client(service)

    responses = [
        client.post(
            "/api/v1/research/papers/parse",
            json={"sourceUrl": "https://publisher.example/paper", "runId": "run-1"},
        ),
        client.get("/api/v1/research/papers/paper-1/sources"),
        client.get("/api/v1/research/papers/paper-1/document"),
        client.get("/api/v1/research/papers/paper-1/catalog"),
        client.get("/api/v1/research/papers/paper-1/code"),
        client.get("/api/v1/research/papers/paper-1/benchmarks", params={"split": "test"}),
        client.get("/api/v1/research/catalog/papers", params={"query": "method", "limit": 3}),
        client.get("/api/v1/research/catalog/leaderboards", params={"metricId": "accuracy"}),
        client.post("/api/v1/research/catalog/refresh", json={"paperId": "paper-1"}),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["data"]["runId"] == "run-1"
    assert responses[0].json()["data"]["artifactRefs"]
    assert {call[0] for call in service.calls} == {
        "parse_paper",
        "get_sources",
        "get_document",
        "get_catalog",
        "get_code",
        "get_benchmarks",
        "list_catalog_papers",
        "get_leaderboards",
        "refresh_catalog",
    }
    benchmark_call = next(call for call in service.calls if call[0] == "get_benchmarks")
    assert benchmark_call[2]["split"] == "test"
    search_call = next(call for call in service.calls if call[0] == "list_catalog_papers")
    assert search_call[2]["limit"] == 3


def test_research_parse_route_requires_source_and_returns_validation_error() -> None:
    client = _client(_CatalogService())

    response = client.post("/api/v1/research/papers/parse", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_research_route_sanitizes_unexpected_application_adapter_errors() -> None:
    class _FailingService(_CatalogService):
        def get_catalog(self, paper_id, *, actor=None):
            raise RuntimeError("secret adapter payload")

    response = _client(_FailingService()).get("/api/v1/research/papers/paper-1/catalog")

    assert response.status_code == 500
    payload = response.json()
    assert payload["error"]["code"] == "research_operation_failed"
    assert payload["error"]["message"] == "Research paper operation failed"
    assert "secret adapter payload" not in response.text
