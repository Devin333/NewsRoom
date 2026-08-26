from __future__ import annotations

import argparse
import inspect
import json
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.deps import build_api_services
from interfaces.cli.commands import mcp as mcp_commands
from interfaces.composition import research as research_composition
from interfaces.composition.research import build_research_application_service
from interfaces.mcp.server import NewsMCPServerAdapter
from interfaces.mcp.stdio_server import handle_jsonrpc_request, run_stdio
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.research_service import ResearchServiceError
from interfaces.services.source_runtime import SourceRuntimeProvider


class _ResearchService:
    def __init__(self) -> None:
        self.paper_ids: list[str] = []

    def get_analysis(self, paper_id: str, *, actor=None) -> dict[str, object]:
        self.paper_ids.append(paper_id)
        return {
            "paperId": paper_id,
            "status": "succeeded",
            "analysis": {"summary": "shared production composition"},
        }


class _CountingProvider:
    def __init__(self, service: _ResearchService) -> None:
        self.service = service
        self.calls = 0
        self.source_runtime_provider = SourceRuntimeProvider()

    def service_factory(self) -> _ResearchService:
        self.calls += 1
        return self.service


class _FailingResearchService:
    def __init__(self, failure_kind: str) -> None:
        self.failure_kind = failure_kind
        self.calls = 0

    def analyze_paper(self, _command) -> dict[str, object]:
        self.calls += 1
        if self.failure_kind == "quality":
            raise ResearchServiceError(
                "quality_gate_failed",
                "research quality gates failed",
                status_code=422,
                details={"gateFailures": [{"gate_id": "ResearchEvidenceGate"}]},
                user_action_required=True,
            )
        if self.failure_kind == "source":
            raise ResearchServiceError(
                "research_run_failed",
                "research run failed",
                status_code=500,
                details={"error_type": "ResearchSourceError"},
                retryable=True,
            )
        if self.failure_kind == "unavailable":
            raise ResearchServiceError(
                "research_runtime_unavailable",
                "Research runtime is unavailable for capabilities: research.llm.credential",
                status_code=503,
                details={
                    "capabilities": ["research.llm.credential"],
                    "remediation": {
                        "code": "configure_research_llm_credential",
                        "message": "Configure the Research LLM credential.",
                    },
                },
                user_action_required=True,
            )
        raise AssertionError(f"unsupported failure kind: {self.failure_kind}")


def _paper_analysis_call(service: MCPApplicationService, paper_id: str):
    return service.call_tool(
        "news.research.paper_analysis",
        {"paper_id": paper_id},
    )


def _analyze_error_surfaces(
    service: _FailingResearchService,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[object, object, dict[str, dict[str, object]]]:
    def research_factory():
        return service

    def mcp_factory(*_args):
        return MCPApplicationService(
            research_service_factory=research_factory,
        )

    monkeypatch.setattr(mcp_commands, "_mcp_service", mcp_factory)
    monkeypatch.setenv("NEWS_PRELOAD_RERANKER", "0")
    monkeypatch.delenv("NEWS_API_KEYS", raising=False)
    arguments = {
        "paper_id": "2607.00001",
        "source_url": "https://arxiv.org/abs/2607.00001",
        "run_id": f"entrypoint-{service.failure_kind}",
    }

    with TestClient(
        create_app(
            research_service_factory=research_factory,
            audit_emitter_factory=None,
        )
    ) as client:
        http_research = client.post(
            "/api/v1/research/papers/analyze",
            json={
                "paperId": arguments["paper_id"],
                "sourceUrl": arguments["source_url"],
                "runId": arguments["run_id"],
            },
        )
        http_mcp = client.post(
            "/api/v1/mcp/tools/news.research.analyze_paper/call",
            json={"arguments": arguments},
        )

    local_payload = mcp_factory().call_tool(
        "news.research.analyze_paper",
        arguments,
    ).to_dict()
    cli_exit = mcp_commands.mcp_call(
        argparse.Namespace(
            tool_name="news.research.analyze_paper",
            args_json=json.dumps(arguments),
            json=True,
        )
    )
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_exit == 1

    stdio_output = StringIO()
    run_stdio(
        input_stream=StringIO(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": f"stdio-{service.failure_kind}",
                    "method": "tools/call",
                    "params": {
                        "name": "news.research.analyze_paper",
                        "arguments": arguments,
                    },
                }
            )
            + "\n"
        ),
        output_stream=stdio_output,
        service=mcp_factory(),
    )
    stdio_payload = json.loads(stdio_output.getvalue())["result"]
    server_payload = NewsMCPServerAdapter(service=mcp_factory()).call_tool(
        "news.research.analyze_paper",
        arguments,
    )
    return http_research, http_mcp, {
        "local_mcp": local_payload,
        "stdio_mcp": stdio_payload,
        "cli_mcp": cli_payload,
        "server_adapter": server_payload,
    }


def test_http_defaults_name_the_shared_production_factory() -> None:
    assert (
        inspect.signature(create_app)
        .parameters["research_service_factory"]
        .default
        is build_research_application_service
    )
    assert (
        inspect.signature(build_api_services)
        .parameters["research_service_factory"]
        .default
        is build_research_application_service
    )


def test_default_entrypoints_do_not_resolve_research_during_construction(
    monkeypatch,
) -> None:
    provider = _CountingProvider(_ResearchService())
    monkeypatch.setattr(
        research_composition,
        "_DEFAULT_RESEARCH_RUNTIME_PROVIDER",
        provider,
    )

    create_app(audit_emitter_factory=None)
    MCPApplicationService().catalog()
    mcp_commands._mcp_service().catalog()
    handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    NewsMCPServerAdapter().catalog()

    assert provider.calls == 0


def test_all_default_entrypoints_resolve_the_shared_research_provider(
    monkeypatch,
    capsys,
) -> None:
    research_service = _ResearchService()
    provider = _CountingProvider(research_service)
    monkeypatch.setattr(
        research_composition,
        "_DEFAULT_RESEARCH_RUNTIME_PROVIDER",
        provider,
    )
    monkeypatch.setenv("NEWS_PRELOAD_RERANKER", "0")

    client = TestClient(create_app(audit_emitter_factory=None))
    http_research = client.get("/api/v1/research/papers/paper-http/analysis")
    http_mcp = client.post(
        "/api/v1/mcp/tools/news.research.paper_analysis/call",
        json={"arguments": {"paper_id": "paper-http-mcp"}},
    )
    local_mcp = _paper_analysis_call(MCPApplicationService(), "paper-local-mcp")

    cli_exit = mcp_commands.mcp_call(
        argparse.Namespace(
            tool_name="news.research.paper_analysis",
            args_json=json.dumps({"paper_id": "paper-cli"}),
            json=True,
        )
    )
    cli_payload = json.loads(capsys.readouterr().out)

    stdio = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "news.research.paper_analysis",
                "arguments": {"paper_id": "paper-stdio"},
            },
        },
    )
    server = NewsMCPServerAdapter().call_tool(
        "news.research.paper_analysis",
        {"paper_id": "paper-server"},
    )

    assert http_research.status_code == 200
    assert http_mcp.status_code == 200
    assert local_mcp.success is True
    assert cli_exit == 0
    assert cli_payload["success"] is True
    assert stdio is not None and stdio["result"]["success"] is True
    assert server["success"] is True
    assert provider.calls == 6
    assert research_service.paper_ids == [
        "paper-http",
        "paper-http-mcp",
        "paper-local-mcp",
        "paper-cli",
        "paper-stdio",
        "paper-server",
    ]


def test_explicit_http_and_mcp_factories_bypass_the_default_provider(
    monkeypatch,
) -> None:
    default_provider = _CountingProvider(_ResearchService())
    explicit_research = _ResearchService()
    explicit_mcp = MCPApplicationService(
        research_service_factory=lambda: explicit_research,
    )
    monkeypatch.setattr(
        research_composition,
        "_DEFAULT_RESEARCH_RUNTIME_PROVIDER",
        default_provider,
    )
    monkeypatch.setenv("NEWS_PRELOAD_RERANKER", "0")

    client = TestClient(
        create_app(
            research_service_factory=lambda: explicit_research,
            audit_emitter_factory=None,
        )
    )
    http_research = client.get("/api/v1/research/papers/paper-http/analysis")
    http_mcp = client.post(
        "/api/v1/mcp/tools/news.research.paper_analysis/call",
        json={"arguments": {"paper_id": "paper-http-mcp"}},
    )
    local_mcp = _paper_analysis_call(explicit_mcp, "paper-local-mcp")
    stdio = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "news.research.paper_analysis",
                "arguments": {"paper_id": "paper-stdio"},
            },
        },
        service=explicit_mcp,
    )
    server = NewsMCPServerAdapter(service=explicit_mcp).call_tool(
        "news.research.paper_analysis",
        {"paper_id": "paper-server"},
    )

    assert http_research.status_code == 200
    assert http_mcp.status_code == 200
    assert local_mcp.success is True
    assert stdio is not None and stdio["result"]["success"] is True
    assert server["success"] is True
    assert default_provider.calls == 0
    assert explicit_research.paper_ids == [
        "paper-http",
        "paper-http-mcp",
        "paper-local-mcp",
        "paper-stdio",
        "paper-server",
    ]


@pytest.mark.parametrize(
    (
        "failure_kind",
        "expected_status",
        "expected_code",
        "expected_error_type",
        "expected_message",
    ),
    [
        (
            "quality",
            422,
            "quality_gate_failed",
            "ResearchQualityGateError",
            "research quality gate failed",
        ),
        (
            "source",
            500,
            "research_run_failed",
            "ResearchSourceError",
            "research source acquisition failed",
        ),
        (
            "unavailable",
            503,
            "research_runtime_unavailable",
            "ResearchRuntimeUnavailableError",
            "research runtime is unavailable",
        ),
    ],
)
def test_research_failures_keep_stable_semantics_across_transports(
    failure_kind: str,
    expected_status: int,
    expected_code: str,
    expected_error_type: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = _FailingResearchService(failure_kind)

    http_research, http_mcp, mcp_payloads = _analyze_error_surfaces(
        service,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert http_research.status_code == expected_status
    assert http_research.json()["error"]["code"] == expected_code
    assert http_mcp.status_code == expected_status
    assert http_mcp.json()["error"]["code"] == expected_code
    assert (
        http_mcp.json()["error"]["details"]["error_type"]
        == expected_error_type
    )
    for payload in mcp_payloads.values():
        assert payload["success"] is False
        assert payload["error_type"] == expected_error_type
        assert payload["error_message"] == expected_message
        assert payload.get("data") is None
    assert service.calls == 6


def test_http_mcp_actor_spoof_preserves_sanitized_forbidden_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_TENANT_ID", "tenant-a")
    monkeypatch.setenv("NEWS_PRELOAD_RERANKER", "0")
    client = TestClient(
        create_app(
            research_service_factory=_ResearchService,
            audit_emitter_factory=None,
            api_keys={"token-a": ["mcp_client"]},
        )
    )

    response = client.post(
        "/api/v1/mcp/tools/news.research.ask/call",
        headers={"Authorization": "Bearer token-a"},
        json={
            "arguments": {
                "paper_id": "paper-1",
                "question": "What is the method?",
                "tenant_id": "tenant-b",
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["message"] == (
        "Research actor scope does not match the authenticated principal"
    )
    assert response.json()["error"]["details"]["error_type"] == (
        "ResearchActorAuthorizationError"
    )
    assert "tenant-b" not in response.text
