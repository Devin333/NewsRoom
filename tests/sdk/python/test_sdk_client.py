from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interfaces.api import create_app
from newsroom_sdk import NewsRoomAPIError, NewsRoomClient
from newsroom_sdk.errors import NewsRoomResponseError
from newsroom_sdk.transport import HttpTransport
from newsroom_sdk.config import NewsRoomConfig
from infrastructure.storage.repository import ReportRecord


def test_client_instantiates_resources() -> None:
    client = NewsRoomClient("https://news.example/", api_key="token")

    assert client.transport.config.base_url == "https://news.example"
    assert client.runs is not None
    assert client.reports is not None
    assert client.memory is not None
    assert client.mcp is not None


def test_transport_sends_auth_request_id_and_unwraps_envelope() -> None:
    calls = []

    def request_func(method, path, *, headers, json=None, params=None, timeout=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "headers": headers,
                "json": json,
                "params": params,
                "timeout": timeout,
            }
        )
        return {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }

    client = NewsRoomClient(
        "https://news.example/",
        api_key="token",
        timeout=5,
        request_func=request_func,
    )

    assert client.memory.search("OpenAI") == {"ok": True}
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/v1/memory/search"
    assert calls[0]["headers"]["Authorization"] == "Bearer token"
    assert calls[0]["headers"]["X-Request-ID"]
    assert calls[0]["timeout"] == 5


def test_transport_maps_api_envelope_error() -> None:
    def request_func(method, path, *, headers, json=None, params=None, timeout=None):
        return _Response(
            404,
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "report_not_found",
                    "message": "missing",
                    "details": {"report_id": "missing"},
                    "retryable": False,
                    "user_action_required": True,
                    "request_id": "req-error",
                },
                "request_id": "req-outer",
                "schema_version": "1.0",
            },
        )

    client = NewsRoomClient("https://news.example", request_func=request_func)

    with pytest.raises(NewsRoomAPIError) as exc_info:
        client.reports.get("missing")

    assert exc_info.value.code == "report_not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.details == {"report_id": "missing"}
    assert exc_info.value.user_action_required is True
    assert exc_info.value.request_id == "req-error"


def test_transport_rejects_non_envelope_response() -> None:
    transport = HttpTransport(
        NewsRoomConfig(base_url="https://news.example"),
        request_func=lambda *args, **kwargs: {"ok": True},
    )

    with pytest.raises(NewsRoomResponseError):
        transport.request("GET", "/api/v1/reports/latest")


def test_client_can_use_fastapi_testclient_without_real_server() -> None:
    test_client = TestClient(
        create_app(
            worker_service_factory=lambda: _FakeWorkerService(),
            report_service_factory=lambda: _FakeReportService(),
            memory_service_factory=lambda: _FakeMemoryService(),
            research_service_factory=lambda: _FakeResearchService(),
            audit_emitter_factory=None,
        )
    )

    def request_func(method, path, *, headers, json=None, params=None, timeout=None):
        return test_client.request(method, path, headers=headers, json=json, params=params)

    client = NewsRoomClient("http://testserver", request_func=request_func)

    run = client.transport.request(
        "POST",
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2401.00001"},
    )
    report = client.reports.latest()
    memory = client.memory.search("OpenAI", limit=3)

    assert run["status"] == "succeeded"
    assert run["paperId"] == "paper-1"
    assert report["report_id"] == "report-sdk"
    assert memory["query"] == "OpenAI"


class _Response:
    def __init__(self, status_code, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeWorkerService:
    pass


class _FakeResearchService:
    def analyze_paper(self, request):
        return {
            "runId": request.run_id or "research-run-sdk",
            "paperId": request.paper_id,
            "status": "succeeded",
            "analysisRef": f"artifact://{request.run_id or 'research-run-sdk'}/analysis",
        }


class _FakeReportService:
    def latest_report(self):
        return ReportRecord(
            report_id="report-sdk",
            run_id="run-sdk",
            status="final",
            title="SDK Report",
            report_json={"title": "SDK Report"},
            report_markdown="# SDK Report",
            quality_score=0.95,
            manifest_path=".newsroom/runs/run-sdk/manifest.json",
        )


class _FakeMemoryService:
    def search(self, *, text, collection, limit, filters=None):
        return _FakeResult(
            {
                "query": text,
                "collection": collection,
                "limit": limit,
                "filters": filters or {},
                "results": [],
                "result_count": 0,
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
