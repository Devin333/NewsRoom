from __future__ import annotations

import pytest

from interfaces.services.research_service import (
    InMemoryResearchRunStore,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchAskInput,
    ResearchServiceError,
)
from tests.interfaces.research_fixtures import FakeAnalyzeUseCase, make_research_result


def test_research_service_analyze_calls_research_application_and_stores_result() -> None:
    use_case = FakeAnalyzeUseCase()
    store = InMemoryResearchRunStore()
    service = ResearchApplicationService(analyze_use_case=use_case, run_store=store)

    response = service.analyze_paper(
        ResearchAnalyzeInput(
            paper_id="paper-1",
            source_url="https://arxiv.org/abs/2606.00001",
            run_id="research-run-1",
            user_id="user-1",
            metadata={"source": "arxiv"},
            options={"max_turns": 8},
        )
    )

    assert response["runId"] == "research-run-1"
    assert response["paperId"] == "paper-1"
    assert response["analysisRef"] == "artifact://research-run-1/analysis"
    assert use_case.calls[0].source_ref == "https://arxiv.org/abs/2606.00001"
    assert use_case.calls[0].options["metadata"] == {"source": "arxiv"}
    assert store.get_latest_by_paper_id("paper-1") is not None


def test_research_service_reader_and_analysis_return_research_payloads() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    analysis = service.get_analysis("paper-1")
    reader = service.get_reader("paper-1")

    assert analysis["analysis"]["summary"]["core_idea"] == "Separate Harness routing from LLM candidate generation."
    assert reader["paper"]["paper_id"] == "paper-1"
    assert reader["document"]["sections"][0]["section_id"] == "sec-intro"
    assert reader["metadata"]["readerPayloadRef"] == "artifact://research-run-1/reader"


def test_research_service_ask_returns_grounded_evidence_refs() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    answer = service.ask_paper(
        "paper-1",
        ResearchAskInput(question="What is the method?", selection={"sourceRefs": ["paper://paper-1/sec-intro"]}),
    )

    assert answer["answer"] == "A controlled PLAN EXECUTE VERIFY runtime."
    assert "paper://paper-1/sec-intro" in answer["evidenceRefs"]
    assert answer["traceRef"] == "harness-trace://research-run-1"


def test_research_service_standardizes_missing_and_quality_errors() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(make_research_result(quality_passed=False)),
        run_store=InMemoryResearchRunStore(),
    )

    with pytest.raises(ResearchServiceError) as missing:
        service.get_analysis("missing-paper")
    assert missing.value.code == "paper_not_found"

    with pytest.raises(ResearchServiceError) as quality:
        service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))
    assert quality.value.code == "quality_gate_failed"
    assert quality.value.details["gateFailures"][0]["gate_name"] == "ResearchReportReadinessGate"


def test_research_service_default_runtime_requires_real_configuration() -> None:
    service = ResearchApplicationService(run_store=InMemoryResearchRunStore())

    with pytest.raises(ResearchServiceError) as exc:
        service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    assert exc.value.code == "research_run_failed"
    assert exc.value.status_code == 503


def test_research_service_does_not_depend_on_old_papers_application_service(monkeypatch) -> None:
    import interfaces.services.paper_service as paper_service

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("old paper service must not be used")

    monkeypatch.setattr(paper_service, "PapersApplicationService", fail_if_constructed)
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )

    response = service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    assert response["status"] == "succeeded"
