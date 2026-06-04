from __future__ import annotations

from framework.harness import FakeArtifactPort

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


def _use_case(rag_runtime: FakeResearchRAGRuntime) -> AnalyzePaperUseCase:
    return AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=rag_runtime,
            artifact_port=FakeArtifactPort(),
        )
    )


def test_rag_missing_evidence_halts_and_writes_gap_report_context() -> None:
    result = _use_case(FakeResearchRAGRuntime(missing_required_evidence=True)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-rag-gap",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            options={"max_replans": 0},
        )
    )

    assert result.status == "halted"
    assert result.rag_context is not None
    assert result.rag_context.gap_report.missing_information == ["experiment", "limitation"]
    assert any(failure["gate"] == "ResearchEvidenceCoverageGate" for failure in result.diagnostics["gate_failures"])


def test_rag_conflict_report_is_preserved_in_context_pack() -> None:
    result = _use_case(FakeResearchRAGRuntime(conflict=True)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-rag-conflict",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
        )
    )

    assert result.succeeded is True
    assert result.rag_context is not None
    assert result.rag_context.gap_report.conflicting_evidence


def test_rag_budget_exhaustion_is_replayable_halt() -> None:
    result = _use_case(FakeResearchRAGRuntime(query_budget_exhausted=True)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-rag-budget",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            options={"max_replans": 0, "rag_max_queries": 1},
        )
    )

    assert result.status == "halted"
    assert result.rag_context is not None
    assert result.rag_context.gap_report.missing_information == ["rag_query_budget_exhausted"]
    assert result.diagnostics["terminal_reason"] == "verification failed and replan budget is exhausted"
