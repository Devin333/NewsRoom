from __future__ import annotations

from copy import deepcopy

import pytest

from framework.harness import (
    FakeArtifactPort,
    HarnessValidationError,
    InMemoryHarnessEventPort,
)

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import (
    ResearchAnalysisResult,
    ResearchSinglePaperRuntime,
    _transcript_from_events,
)
from business.research.domain import PaperSourceRecord
from business.research.workflows.paper_analysis_gates import PAPER_ANALYSIS_GATE_REFERENCES
from infrastructure.research import ResearchDocumentCompilerAdapter
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
    rag_entry = next(
        entry
        for entry in result.transcript.entries()
        if entry.step_id == "run_research_rag"
        and entry.metadata["event_type"] == "worker_result_recorded"
    )
    assert result.rag_context is not None
    rag_metadata = result.rag_context.metadata
    assert rag_entry.rag_session_refs == (
        f"rag-session://{rag_metadata['session_id']}",
    )
    assert rag_entry.context_pack_refs == (rag_metadata["context_pack_id"],)
    assert rag_entry.output_refs == (
        rag_metadata["transcript_ref"],
        rag_metadata["context_pack_id"],
    )
    assert {
        key: rag_entry.metadata[key]
        for key in (
            "parent_run_id",
            "parent_workflow_id",
            "parent_step_id",
            "workflow_id",
            "step_id",
            "session_id",
        )
    } == {
        "parent_run_id": result.run_id,
        "parent_workflow_id": "research.paper_analysis",
        "parent_step_id": "run_research_rag",
        "workflow_id": "research.paper_analysis",
        "step_id": "run_research_rag",
        "session_id": rag_metadata["session_id"],
    }
    domain_gate_refs_by_step: dict[str, list[str]] = {}
    active_refs = set(PAPER_ANALYSIS_GATE_REFERENCES)
    for event in result.trace.events:
        event_payload = event.to_dict()
        gate_ref = (
            event_payload.get("payload", {})
            .get("details", {})
            .get("harness_gate", {})
            .get("reference")
        )
        if gate_ref in active_refs:
            domain_gate_refs_by_step.setdefault(str(event_payload.get("step_id")), []).append(gate_ref)
    assert domain_gate_refs_by_step == {
        "load_paper_source": ["PaperSourceLineageGate@1"],
        "compile_document": ["ResearchDocumentSchemaGate@1"],
        "run_research_rag": ["ResearchRAGContextProjectionGate@1"],
        "build_evidence_pack": ["ResearchEvidenceCoverageGate@1"],
        "analyze_structure": ["SummarySchemaGate@1"],
        "analyze_contribution": ["SummaryEvidenceCoverageGate@1"],
        "analyze_experiments": ["BenchmarkEvidenceLineageGate@1"],
        "verify_claims": ["ClaimEvidenceGate@1"],
        "quality_gate": ["ResearchQualityGate@1"],
        "build_reader_payload": ["ReaderPayloadSchemaGate@1"],
        "build_paper_card": ["ResearchPaperCardGate@1"],
    }
    assert all(
        "quality_score" not in worker_result["output"]
        for worker_result in result.diagnostics["worker_results"].values()
    )


def test_analysis_result_persistence_round_trip_preserves_typed_runtime_state() -> None:
    result = AnalyzePaperUseCase(_runtime()).analyze(
        AnalyzePaperRequest(
            run_id="research-run-persistence",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    payload = result.to_persistence_dict()
    restored = ResearchAnalysisResult.from_dict(payload)

    assert restored.to_persistence_dict() == payload
    assert isinstance(restored.analysis, type(result.analysis))
    assert isinstance(restored.reader_payload, type(result.reader_payload))
    assert isinstance(restored.trace, type(result.trace))
    assert isinstance(restored.transcript, type(result.transcript))
    assert sum(
        event.deterministic_history is not None for event in restored.trace.events
    ) == sum(event.deterministic_history is not None for event in result.trace.events)
    assert payload["actor_scope"] == {
        "user_id": "user-1",
        "memory_namespace": "research:user:user-1",
    }

    foreign_trace = deepcopy(payload)
    foreign_trace["trace"]["run_id"] = "foreign-run"
    with pytest.raises(HarnessValidationError, match="run_id must match"):
        ResearchAnalysisResult.from_dict(foreign_trace)

    unsupported = deepcopy(payload)
    unsupported["unsafe_extension"] = {"pickle": True}
    with pytest.raises(ValueError, match="unsupported fields"):
        ResearchAnalysisResult.from_dict(unsupported)

    foreign_paper = deepcopy(payload)
    foreign_paper["trace"]["metadata"]["paper_id"] = "foreign-paper"
    with pytest.raises(ValueError, match="paper identity mismatch"):
        ResearchAnalysisResult.from_dict(foreign_paper)

    missing_actor_scope = deepcopy(payload)
    missing_actor_scope.pop("actor_scope")
    with pytest.raises(ValueError, match="field is required: actor_scope"):
        ResearchAnalysisResult.from_dict(missing_actor_scope)

    foreign_transcript_actor = deepcopy(payload)
    foreign_transcript_actor["transcript"]["entries"][0]["metadata"].update(
        {
            "user_id": "foreign-user",
            "memory_namespace": "research:user:foreign-user",
        }
    )
    with pytest.raises(ValueError, match="actor scope mismatch"):
        ResearchAnalysisResult.from_dict(foreign_transcript_actor)

    missing_context_actor = deepcopy(payload)
    missing_context_actor["context_envelope"]["metadata"].pop(
        "memory_namespace"
    )
    with pytest.raises(ValueError, match="actor scope"):
        ResearchAnalysisResult.from_dict(missing_context_actor)


def test_rag_transcript_projection_fails_closed_on_identity_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="Research RAG transcript workflow_id identity mismatch",
    ):
        AnalyzePaperUseCase(
            _runtime(rag_runtime=_MismatchedResearchRAGRuntime())
        ).analyze(
            AnalyzePaperRequest(
                run_id="research-run-rag-identity-mismatch",
                paper_id="paper-harness-001",
                source_ref="https://arxiv.org/abs/2606.00123",
                user_id="user-1",
            )
        )


def test_rag_transcript_projection_rejects_single_sided_context_identity() -> None:
    rag_runtime = FakeResearchRAGRuntime()
    result = AnalyzePaperUseCase(_runtime(rag_runtime=rag_runtime)).analyze(
        AnalyzePaperRequest(
            run_id="research-run-rag-single-sided",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )
    assert result.rag_context is not None
    assert rag_runtime.last_context_pack is not None

    for research_rag_context, rag_context_pack in (
        (result.rag_context, None),
        (None, rag_runtime.last_context_pack),
    ):
        with pytest.raises(ValueError, match="must be provided together"):
            _transcript_from_events(
                result.run_id,
                list(result.trace.events),
                research_rag_context=research_rag_context,
                rag_context_pack=rag_context_pack,
            )


def test_single_paper_loop_does_not_query_github_without_code_url() -> None:
    source_provider = FakeResearchSourceProvider()
    source_provider.paper = source_provider.paper.model_copy(update={"code_url": None})
    github = _NoCallGithubRepository()

    result = AnalyzePaperUseCase(
        _runtime(source_provider=source_provider, github_repository=github)
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-run-without-code",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert github.calls == []
    assert result.paper_card is not None
    assert result.paper_card.github_repo is None
    assert result.paper_card.github_stars is None
    assert result.paper_card.metadata["code_repository_status"] == "missing"
    assert result.paper_card.metadata["code_repository_diagnostics"] == [
        "code_repository_missing"
    ]
    assert result.diagnostics["research_diagnostics"] == ["code_repository_missing"]


@pytest.mark.parametrize(
    ("case_id", "source_ref"),
    [
        ("identifier", "2606.00123"),
        ("http-abs", "http://www.arxiv.org/abs/2606.00123"),
        ("pdf", "https://arxiv.org/pdf/2606.00123.pdf"),
        ("e-print", "https://export.arxiv.org/e-print/2606.00123"),
        ("source", "https://arxiv.org/src/2606.00123"),
    ],
)
def test_paper_card_gate_accepts_verified_arxiv_source_aliases(
    case_id: str,
    source_ref: str,
) -> None:
    result = AnalyzePaperUseCase(_runtime()).analyze(
        AnalyzePaperRequest(
            run_id=f"research-source-alias-{case_id}",
            paper_id="paper-harness-001",
            source_ref=source_ref,
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert result.paper_card is not None
    assert result.paper_card.source_url == "https://arxiv.org/abs/2606.00123"


def test_paper_card_gate_accepts_resolved_version_for_unversioned_request() -> None:
    result = AnalyzePaperUseCase(
        _runtime(source_provider=_ResolvedVersionSourceProvider())
    ).analyze(
        AnalyzePaperRequest(
            run_id="research-resolved-version",
            paper_id="paper-harness-001",
            source_ref="2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert result.paper_card is not None
    assert result.paper_card.source_url == "https://arxiv.org/abs/2606.00123v2"


@pytest.mark.parametrize("compile_path", ["latex", "pdf", "abstract"])
def test_real_document_adapter_passes_hash_continuity_gate(compile_path: str) -> None:
    if compile_path == "latex":
        compiler = ResearchDocumentCompilerAdapter(
            latex_compiler=_ParserHashCompiler(),
        )
    elif compile_path == "pdf":
        compiler = ResearchDocumentCompilerAdapter(
            _RecordedPdfFetcher(),
            latex_compiler=_FailingCompiler(),
            pdf_parser=_ParserHashPdfParser(),
        )
    else:
        compiler = ResearchDocumentCompilerAdapter()

    result = AnalyzePaperUseCase(
        _runtime(
            source_provider=_MetadataSourceProvider(),
            document_compiler=compiler,
        )
    ).analyze(
        AnalyzePaperRequest(
            run_id=f"research-hash-continuity-{compile_path}",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    compile_gate = next(
        event.to_dict()
        for event in result.trace.events
        if event.event_type.value == "gate_evaluated"
        and event.step_id == "compile_document"
    )
    assert compile_gate["payload"]["passed"] is True


def test_reader_payload_gate_failure_halts_without_publishing_failed_payload() -> None:
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

    assert result.status == "halted"
    assert result.reader_issue is not None
    assert result.reader_issue.error_signature == "no_sections"
    assert result.paper_card is None
    assert result.artifact_refs == {}

    foreign_issue = result.to_persistence_dict()
    assert foreign_issue["reader_issue"] is not None
    foreign_issue["reader_issue"]["run_id"] = "foreign-run"
    with pytest.raises(ValueError, match="reader issue run_id mismatch"):
        ResearchAnalysisResult.from_dict(foreign_issue)


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
    failure = next(
        failure
        for failure in result.diagnostics["gate_failures"]
        if failure["gate"] == "BenchmarkEvidenceLineageGate"
    )
    assert failure["details"]["harness_gate"]["reference"] == "BenchmarkEvidenceLineageGate@1"


class _NoCallGithubRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_profile(self, repo_url: str):
        self.calls.append(repo_url)
        raise AssertionError("GitHub must not be queried without paper.code_url")


class _MismatchedResearchRAGRuntime(FakeResearchRAGRuntime):
    def run(self, *, session_spec, document):
        context = super().run(session_spec=session_spec, document=document)
        return context.model_copy(
            update={
                "metadata": {
                    **context.metadata,
                    "workflow_id": "research.foreign_workflow",
                }
            }
        )


class _MetadataSourceProvider(FakeResearchSourceProvider):
    def fetch_source_record(self, paper_id: str) -> PaperSourceRecord:
        return super().fetch_source_record(paper_id).model_copy(
            update={
                "metadata": {
                    "title": self.paper.title,
                    "abstract": self.paper.abstract,
                }
            }
        )


class _ResolvedVersionSourceProvider(_MetadataSourceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.paper = self.paper.model_copy(
            update={
                "source_url": "https://arxiv.org/abs/2606.00123v2",
                "pdf_url": "https://arxiv.org/pdf/2606.00123v2.pdf",
            }
        )

    def fetch_source_record(self, paper_id: str) -> PaperSourceRecord:
        return super().fetch_source_record(paper_id).model_copy(
            update={"source_url": self.paper.source_url}
        )


def _parser_hash_document(paper_id: str):
    source = PaperSourceRecord(
        source_id="parser-source",
        paper_id=paper_id,
        source_type="arxiv",
        source_url="https://arxiv.org/abs/2606.00123",
        source_hash="verified-source-hash",
    )
    document = FakeResearchDocumentCompiler().compile(source)
    return document.model_copy(
        update={
            "source_hash": "parser-content-hash",
            "lineage": document.lineage.model_copy(
                update={"source_hash": "parser-content-hash"}
            ),
        }
    )


class _ParserHashCompiler:
    def compile(self, source: PaperSourceRecord):
        return _parser_hash_document(source.paper_id)


class _FailingCompiler:
    def compile(self, source: PaperSourceRecord):
        raise RuntimeError("recorded latex failure")


class _ParserHashPdfParser:
    def parse(self, paper_id: str, content: bytes):
        assert content == b"%PDF-recorded"
        return _parser_hash_document(paper_id)


class _RecordedPdfPackage:
    content = b"%PDF-recorded"
    checksum = "pdf-package-checksum"


class _RecordedPdfFetcher:
    def fetch_pdf_package(self, arxiv_id: str):
        assert arxiv_id == "2606.00123"
        return _RecordedPdfPackage()
