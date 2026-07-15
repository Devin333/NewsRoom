from __future__ import annotations

from framework.harness import FakeArtifactPort, InMemoryHarnessEventPort

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


def _runtime(**overrides):
    artifact_port = overrides.pop("artifact_port", FakeArtifactPort())
    return ResearchSinglePaperRuntime(
        source_provider=overrides.pop("source_provider", FakeResearchSourceProvider()),
        document_compiler=overrides.pop("document_compiler", FakeResearchDocumentCompiler()),
        llm_worker=overrides.pop("llm_worker", FakeResearchLLMWorker()),
        github_repository=overrides.pop("github_repository", FakeGithubRepositoryPort()),
        rag_runtime=overrides.pop("rag_runtime", FakeResearchRAGRuntime()),
        artifact_port=artifact_port,
        event_port_factory=overrides.pop(
            "event_port_factory",
            lambda run_id: InMemoryHarnessEventPort(),
        ),
    )


def test_single_paper_loop_outputs_artifacts_trace_and_transcript() -> None:
    artifact_port = FakeArtifactPort()
    result = AnalyzePaperUseCase(_runtime(artifact_port=artifact_port)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-integration",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert artifact_port.read_artifact(result.artifact_refs["research-analysis"])["artifact_type"] == "research-analysis"
    assert artifact_port.read_artifact(result.artifact_refs["harness-trace"])["artifact_type"] == "harness-trace"
    assert artifact_port.read_artifact(result.artifact_refs["harness-transcript"])["artifact_type"] == "harness-transcript"
    assert any(entry.phase == "PLAN" for entry in result.transcript.entries())
    assert any(entry.phase == "EXECUTE" for entry in result.transcript.entries())
    assert any(entry.phase == "VERIFY" for entry in result.transcript.entries())


def test_reader_payload_gate_failure_routes_to_issue_artifact_without_repair_rag() -> None:
    result = AnalyzePaperUseCase(
        _runtime(document_compiler=FakeResearchDocumentCompiler(omit_sections=True))
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-reader-issue",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.status == "succeeded"
    assert result.reader_issue is not None
    assert result.reader_issue.error_signature == "no_sections"
    assert result.paper_card is not None
    assert result.paper_card.reader_payload_status == "needs_repair"
    assert "reader-issue" in result.artifact_refs
    assert "research-rag-gap-report" not in result.artifact_refs


def test_score_range_gate_halts_invalid_score() -> None:
    result = AnalyzePaperUseCase(
        _runtime(llm_worker=FakeResearchLLMWorker(score_value=2_000_000_000))
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-score-range",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            options={"max_replans": 0},
        )
    )

    assert result.status == "halted"
    assert any(failure["gate"] == "ResearchScoreRangeGate" for failure in result.diagnostics["gate_failures"])
