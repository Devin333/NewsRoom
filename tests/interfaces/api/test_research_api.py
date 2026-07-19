from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.research_service import InMemoryResearchRunStore, ResearchApplicationService
from tests.interfaces.research_fixtures import FakeAnalyzeUseCase, make_research_result


def _client(*, result=None):
    store = InMemoryResearchRunStore()
    use_case = FakeAnalyzeUseCase(result or make_research_result())
    service = ResearchApplicationService(analyze_use_case=use_case, run_store=store)
    return TestClient(
        create_app(
            research_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )


def test_research_analyze_endpoint_returns_run_id_and_refs() -> None:
    client = _client()

    response = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2606.00001",
            "metadata": {"source": "arxiv"},
            "options": {"max_turns": 8},
            "runId": "research-run-1",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["runId"] == "research-run-1"
    assert payload["data"]["analysisRef"] == "artifact://research-run-1/analysis"
    assert payload["data"]["readerPayloadRef"] == "artifact://research-run-1/reader"
    assert payload["data"]["traceRef"] == "harness-trace://research-run-1"


def test_research_http_transports_actor_scope_for_analyze_and_both_ask_modes() -> None:
    service = _CapturingResearchService()
    client = TestClient(
        create_app(
            research_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )
    actor = {
        "tenantId": "tenant-a",
        "userId": "user-1",
        "memoryNamespace": "research:tenant:tenant-a:user:user-1",
    }

    analyzed = client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2606.00001",
            **actor,
        },
    )
    asked = client.post(
        "/api/v1/research/papers/paper-1/ask",
        json={"question": "What is the method?", **actor},
    )
    rag_asked = client.post(
        "/api/v1/research/papers/paper-1/rag-ask",
        json={
            "question": "What evidence supports the method?",
            "sectionIndex": 2,
            "limit": 7,
            "generate": True,
            **actor,
        },
    )

    assert analyzed.status_code == 200
    assert asked.status_code == 200
    assert rag_asked.status_code == 200
    analyze_input = service.analyze_inputs[0]
    ask_input, rag_ask_input = service.ask_inputs
    assert (
        analyze_input.tenant_id,
        analyze_input.user_id,
        analyze_input.memory_namespace,
    ) == (
        "tenant-a",
        "user-1",
        "research:tenant:tenant-a:user:user-1",
    )
    assert rag_ask_input.mode == "chunk_rag"
    assert rag_ask_input.section_index == 2
    assert rag_ask_input.limit == 7
    assert rag_ask_input.generate is True
    assert (
        rag_ask_input.tenant_id,
        rag_ask_input.user_id,
        rag_ask_input.memory_namespace,
    ) == (
        "tenant-a",
        "user-1",
        "research:tenant:tenant-a:user:user-1",
    )
    assert (
        ask_input.tenant_id,
        ask_input.user_id,
        ask_input.memory_namespace,
    ) == (
        "tenant-a",
        "user-1",
        "research:tenant:tenant-a:user:user-1",
    )


def test_authenticated_research_http_binds_deployment_tenant_and_rejects_spoof(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEWS_TENANT_ID", "tenant-a")
    service = _CapturingResearchService()
    client = TestClient(
        create_app(
            research_service_factory=lambda: service,
            api_keys={"token-a": ["service"]},
            audit_emitter_factory=None,
        )
    )
    headers = {"Authorization": "Bearer token-a"}

    analyzed = client.post(
        "/api/v1/research/papers/analyze",
        headers=headers,
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2606.00001",
        },
    )
    spoofed = client.post(
        "/api/v1/research/papers/paper-1/ask",
        headers=headers,
        json={
            "question": "What is the method?",
            "tenantId": "tenant-b",
        },
    )

    assert analyzed.status_code == 200
    assert service.analyze_inputs[0].tenant_id == "tenant-a"
    assert (
        service.analyze_inputs[0].memory_namespace
        == "research:tenant:tenant-a:public"
    )
    assert spoofed.status_code == 403
    assert spoofed.json()["error"]["code"] == "forbidden"
    assert service.ask_inputs == []


def test_research_reader_analysis_ask_and_trace_endpoints_return_research_payloads() -> None:
    client = _client()
    client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2606.00001", "runId": "research-run-1"},
    )

    analysis = client.get("/api/v1/research/papers/paper-1/analysis")
    reader = client.get("/api/v1/research/papers/paper-1/reader")
    ask = client.post("/api/v1/research/papers/paper-1/ask", json={"question": "What is the method?"})
    trace = client.get("/api/v1/research/runs/research-run-1/trace")

    assert analysis.status_code == 200
    assert analysis.json()["data"]["analysis"]["summary"]["method_summary"] == "A controlled PLAN EXECUTE VERIFY runtime."
    assert reader.status_code == 200
    assert reader.json()["data"]["paper"]["paper_id"] == "paper-1"
    assert ask.status_code == 200
    assert ask.json()["data"]["evidenceRefs"]
    assert trace.status_code == 200
    assert trace.json()["data"]["trace"]["events"][0]["event_type"] == "phase_started"


def test_research_api_returns_stable_error_codes_without_tracebacks() -> None:
    client = _client(result=make_research_result(quality_passed=False))

    missing = client.get("/api/v1/research/papers/missing/analysis")
    failed_quality = client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2606.00001"},
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "paper_not_found"
    assert "Traceback" not in missing.text
    assert failed_quality.status_code == 422
    assert failed_quality.json()["error"]["code"] == "quality_gate_failed"
    assert "Traceback" not in failed_quality.text


def test_research_api_requires_matching_actor_for_tenant_queries() -> None:
    result = make_research_result(run_id="run-tenant-a", paper_id="paper-1")
    result.trace["metadata"] = {
        "tenant_id": "tenant-a",
        "user_id": "user-1",
        "memory_namespace": "research:tenant:tenant-a:user:user-1",
    }
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(result),
        run_store=InMemoryResearchRunStore(),
    )
    client = TestClient(
        create_app(
            research_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )
    actor = {
        "tenantId": "tenant-a",
        "userId": "user-1",
        "memoryNamespace": "research:tenant:tenant-a:user:user-1",
    }
    client.post(
        "/api/v1/research/papers/analyze",
        json={
            "paperId": "paper-1",
            "sourceUrl": "https://arxiv.org/abs/2606.00001",
            "runId": "run-tenant-a",
            **actor,
        },
    )

    hidden_analysis = client.get("/api/v1/research/papers/paper-1/analysis")
    hidden_trace = client.get("/api/v1/research/runs/run-tenant-a/trace")
    visible_analysis = client.get(
        "/api/v1/research/papers/paper-1/analysis",
        params=actor,
    )
    visible_reader = client.get(
        "/api/v1/research/papers/paper-1/reader",
        params=actor,
    )
    visible_trace = client.get(
        "/api/v1/research/runs/run-tenant-a/trace",
        params=actor,
    )

    assert hidden_analysis.status_code == 404
    assert hidden_trace.status_code == 404
    assert visible_analysis.status_code == 200
    assert visible_analysis.json()["data"]["runId"] == "run-tenant-a"
    assert visible_reader.status_code == 200
    assert visible_reader.json()["data"]["metadata"]["runId"] == "run-tenant-a"
    assert visible_trace.status_code == 200
    assert visible_trace.json()["data"]["runId"] == "run-tenant-a"


def test_research_api_does_not_use_old_paper_service_or_old_papers_routes() -> None:
    client = _client()
    response = client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2606.00001"},
    )
    old_route = client.get("/api/v1/papers/paper-1")

    assert response.status_code == 200
    assert response.json()["data"]["paperId"] == "paper-1"
    assert old_route.status_code == 404


class _CapturingResearchService:
    def __init__(self) -> None:
        self.analyze_inputs = []
        self.ask_inputs = []

    def analyze_paper(self, command):
        self.analyze_inputs.append(command)
        return {
            "runId": command.run_id or "run-actor",
            "paperId": command.paper_id,
            "status": "succeeded",
        }

    def ask_paper(self, paper_id, request):
        self.ask_inputs.append(request)
        return {
            "answer": "Grounded answer",
            "evidenceRefs": [f"paper://{paper_id}/sec-method"],
            "confidence": 1.0,
        }
