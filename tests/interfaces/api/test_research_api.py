from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.research_service import InMemoryResearchRunStore, ResearchApplicationService
from tests.interfaces.research_fixtures import FakeAnalyzeUseCase, make_research_result


def _client(*, result=None, paper_service_factory=None):
    store = InMemoryResearchRunStore()
    use_case = FakeAnalyzeUseCase(result or make_research_result())
    service = ResearchApplicationService(analyze_use_case=use_case, run_store=store)
    return TestClient(
        create_app(
            research_service_factory=lambda: service,
            papers_service_factory=paper_service_factory or _unused_paper_service_factory,
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


def test_research_api_does_not_use_old_paper_service_or_old_papers_routes() -> None:
    def old_paper_service_must_not_be_used():
        raise AssertionError("old paper service must not be used")

    client = _client(paper_service_factory=old_paper_service_must_not_be_used)
    response = client.post(
        "/api/v1/research/papers/analyze",
        json={"paperId": "paper-1", "sourceUrl": "https://arxiv.org/abs/2606.00001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["paperId"] == "paper-1"


def _unused_paper_service_factory():
    raise AssertionError("old paper service must not be used by research API tests")
