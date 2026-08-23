from __future__ import annotations

from framework.harness import (
    FakeArtifactPort,
    HarnessEventType,
    InMemoryHarnessEventPort,
)

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
    in_memory_node_output_resource_factory,
)
from tests.framework.harness.context.runtime_fakes import verified_context_assembler


def test_rag_context_writes_snapshot_before_llm_visible_artifacts() -> None:
    artifact_port = FakeArtifactPort()
    context_assembler, _, context_events = verified_context_assembler(
        artifact_port=artifact_port
    )
    result = AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=FakeResearchRAGRuntime(),
            artifact_port=artifact_port,
            node_output_resource_factory=in_memory_node_output_resource_factory,
            event_port_factory=lambda run_id: InMemoryHarnessEventPort(),
            context_assembler=context_assembler,
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
    assert result.context_envelope.metadata["context_verification_classification"] == (
        "versioned_no_compaction_evidence"
    )
    assert result.context_envelope.metadata["context_dispatch_authorized"] is False
    assert result.context_envelope.metadata[
        "context_dispatch_authorization_required"
    ] is True
    assert context_events.events[-1].event_type is HarnessEventType.CONTEXT_COMPACTION_PLANNED


def test_protected_research_context_overflow_fails_closed() -> None:
    artifact_port = FakeArtifactPort()
    context_assembler, _, context_events = verified_context_assembler(
        artifact_port=artifact_port
    )
    use_case = AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=FakeResearchRAGRuntime(),
            artifact_port=artifact_port,
            node_output_resource_factory=in_memory_node_output_resource_factory,
            event_port_factory=lambda run_id: InMemoryHarnessEventPort(),
            context_assembler=context_assembler,
        )
    )

    result = use_case.analyze(
        AnalyzePaperRequest(
            run_id="research-run-context-compression",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
            options={
                "context_max_input_tokens": 256,
                "evidence_memory_tokens": 900,
            },
        )
    )

    assert result.status == "failed"
    assert result.diagnostics["terminal_reason"] == "graph_terminal_failure"
    publish_result = next(
        item
        for item in result.diagnostics["worker_results"].values()
        if item["node_id"] == "publish_artifacts"
    )
    assert publish_result["error"] == (
        "verified context runtime did not authorize provider dispatch"
    )
    assert HarnessEventType.CONTEXT_COMPACTION_VERIFIED not in {
        event.event_type for event in context_events.events
    }
    assert context_assembler.events[-1]["event_type"] == "context_compaction_rejected"


def test_request_cannot_expand_the_composition_context_limit() -> None:
    artifact_port = FakeArtifactPort()
    context_assembler, _, _ = verified_context_assembler(
        max_input_tokens=8_192,
        artifact_port=artifact_port,
    )
    result = AnalyzePaperUseCase(
        ResearchSinglePaperRuntime(
            source_provider=FakeResearchSourceProvider(),
            document_compiler=FakeResearchDocumentCompiler(),
            llm_worker=FakeResearchLLMWorker(),
            github_repository=FakeGithubRepositoryPort(),
            rag_runtime=FakeResearchRAGRuntime(),
            artifact_port=artifact_port,
            node_output_resource_factory=in_memory_node_output_resource_factory,
            event_port_factory=lambda run_id: InMemoryHarnessEventPort(),
            context_assembler=context_assembler,
            context_max_input_tokens=8_192,
        )
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-context-policy-cap",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
            options={"context_max_input_tokens": 32_768},
        )
    )

    assert result.context_envelope is not None
    assert result.context_envelope.budget is not None
    assert result.context_envelope.budget.max_input_tokens == 8_192
