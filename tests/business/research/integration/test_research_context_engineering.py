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


def test_rag_context_writes_snapshot_before_llm_visible_artifacts() -> None:
    result = AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=FakeResearchRAGRuntime(),
            artifact_port=FakeArtifactPort(),
        )
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-context",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.context_snapshot is not None
    assert result.context_envelope is not None
    assert result.context_envelope.snapshot_ref == result.context_snapshot.snapshot_id
    assert result.context_envelope.evidence_refs
    stable_prefix = result.context_envelope.stable_prefix
    assert "evidence_memory" not in stable_prefix
    assert "github_metrics" not in str(stable_prefix)
    assert "full_paper_text" not in str(stable_prefix)
    assert "research-context-snapshot" in result.artifact_refs


def test_context_compression_preserves_source_refs_and_budget() -> None:
    result = AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=FakeResearchRAGRuntime(),
            artifact_port=FakeArtifactPort(),
        )
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-context-compression",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
            options={"context_max_input_tokens": 256, "evidence_memory_tokens": 900},
        )
    )

    assert result.context_snapshot is not None
    assert result.compression_records
    record = result.compression_records[0]
    assert record["lost_fields"] == []
    assert "paper://paper-harness-001/sec-method" in record["preserved_refs"]
    assert "research-context-compression-records" in result.artifact_refs
