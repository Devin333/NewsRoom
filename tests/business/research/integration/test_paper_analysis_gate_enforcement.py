from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from framework.harness import (
    DeterministicGateRegistry,
    FakeArtifactPort,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
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
)


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_OutputMutator = Callable[[dict[str, Any]], None]


class _RecordingResearchSourceProvider(FakeResearchSourceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def fetch_paper(self, source_url: str):
        self.calls.append(("fetch_paper", source_url))
        return super().fetch_paper(source_url)

    def fetch_source_record(self, paper_id: str):
        self.calls.append(("fetch_source_record", paper_id))
        return super().fetch_source_record(paper_id)


def _switch_document_scope(output: dict[str, Any]) -> None:
    output["document"]["paper_id"] = "other-paper"
    output["document"]["lineage"]["source_refs"] = ["source://other-paper"]
    output["source_refs"] = ["source://other-paper"]


def _switch_document_source_scope(output: dict[str, Any]) -> None:
    output["document"]["lineage"]["source_refs"] = ["source://foreign/sec-method"]
    for section in output["document"]["sections"]:
        section["source_ref"] = f"source://foreign/{section['section_id']}"
    output["source_refs"] = ["source://foreign/sec-method"]


def _switch_rag_paper_scope(output: dict[str, Any]) -> None:
    context = output["research_rag_context"]
    context["paper_id"] = "other-paper"
    context["goal"]["paper_id"] = "other-paper"


def _switch_rag_source_scope(output: dict[str, Any]) -> None:
    context = output["research_rag_context"]
    context["goal"]["allowed_source_refs"] = ["source://other-paper"]
    context["source_refs"] = ["source://other-paper"]
    context["lineage"]["source_refs"] = ["source://other-paper"]
    output["source_refs"] = ["source://other-paper"]


def _switch_evidence_paper_scope(output: dict[str, Any]) -> None:
    pack = output["evidence_pack"]
    pack["paper_id"] = "other-paper"
    for item in pack["items"]:
        item["paper_id"] = "other-paper"


def _switch_evidence_source_scope(output: dict[str, Any]) -> None:
    pack = output["evidence_pack"]
    pack["lineage"]["source_refs"] = ["source://other-paper"]
    output["source_refs"] = ["source://other-paper"]
    for item in pack["items"]:
        item["source_ref"] = "source://other-paper"
        item["lineage"]["source_refs"] = ["source://other-paper"]


def _switch_summary_evidence_scope(output: dict[str, Any]) -> None:
    output["summary_evidence_refs"][0]["evidence_id"] = "evidence-other-paper"
    output["summary_evidence_refs"][0]["source_ref"] = "source://other-paper"


def _switch_quality_scope(output: dict[str, Any]) -> None:
    output["analysis"]["paper_id"] = "other-paper"
    output["research_quality"]["target_id"] = "other-paper"


def _switch_reader_scope(output: dict[str, Any]) -> None:
    payload = output["reader_payload"]
    payload["paper"]["paper_id"] = "other-paper"
    payload["document"]["paper_id"] = "other-paper"
    if payload.get("analysis") is not None:
        payload["analysis"]["paper_id"] = "other-paper"
    if payload.get("evidence") is not None:
        payload["evidence"]["paper_id"] = "other-paper"


def _switch_paper_card_scope(output: dict[str, Any]) -> None:
    output["paper_card"]["paper_id"] = "other-paper"
    output["paper_card"]["source_url"] = "https://example.invalid/other-paper"


def test_incomplete_research_registry_fails_before_source_or_artifact_calls() -> None:
    source_provider = _RecordingResearchSourceProvider()
    artifact_port = FakeArtifactPort()
    event_port = InMemoryHarnessEventPort()
    runtime = ResearchSinglePaperRuntime(
        source_provider=source_provider,
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=artifact_port,
        event_port_factory=lambda run_id: event_port,
    )
    runtime.gate_registry = DeterministicGateRegistry()

    with pytest.raises(HarnessValidationError) as missing:
        AnalyzePaperUseCase(runtime).analyze(
            AnalyzePaperRequest(
                run_id="missing-research-gate-registry",
                paper_id="paper-harness-001",
                source_ref="https://arxiv.org/abs/2606.00123",
            )
        )

    assert missing.value.code == "unknown_gate_reference"
    assert source_provider.calls == []
    assert artifact_port.storage == {}
    assert event_port.events == []


@pytest.mark.parametrize(
    ("step_id", "gate_reference", "next_step_id", "mutator", "uses_controlled_repair"),
    (
        pytest.param(
            "load_paper_source",
            "PaperSourceLineageGate@1",
            "compile_document",
            lambda output: output.__setitem__("source_refs", []),
            False,
            id="paper-source-lineage",
        ),
        pytest.param(
            "compile_document",
            "ResearchDocumentSchemaGate@1",
            "run_research_rag",
            lambda output: output["document"]["lineage"].__setitem__("source_refs", []),
            False,
            id="document-schema",
        ),
        pytest.param(
            "compile_document",
            "ResearchDocumentSchemaGate@1",
            "run_research_rag",
            _switch_document_scope,
            False,
            id="document-run-scope",
        ),
        pytest.param(
            "compile_document",
            "ResearchDocumentSchemaGate@1",
            "run_research_rag",
            _switch_document_source_scope,
            False,
            id="document-source-record-scope",
        ),
        pytest.param(
            "run_research_rag",
            "ResearchRAGContextProjectionGate@1",
            "build_evidence_pack",
            lambda output: output["research_rag_context"].__setitem__("context_id", ""),
            False,
            id="rag-context-projection",
        ),
        pytest.param(
            "run_research_rag",
            "ResearchRAGContextProjectionGate@1",
            "build_evidence_pack",
            _switch_rag_paper_scope,
            False,
            id="rag-paper-scope",
        ),
        pytest.param(
            "run_research_rag",
            "ResearchRAGContextProjectionGate@1",
            "build_evidence_pack",
            _switch_rag_source_scope,
            False,
            id="rag-source-scope",
        ),
        pytest.param(
            "build_evidence_pack",
            "ResearchEvidenceCoverageGate@1",
            "analyze_structure",
            lambda output: output["evidence_pack"].__setitem__(
                "missing_information",
                ["missing_control_evidence"],
            ),
            False,
            id="evidence-coverage",
        ),
        pytest.param(
            "build_evidence_pack",
            "ResearchEvidenceCoverageGate@1",
            "analyze_structure",
            _switch_evidence_paper_scope,
            False,
            id="evidence-paper-scope",
        ),
        pytest.param(
            "build_evidence_pack",
            "ResearchEvidenceCoverageGate@1",
            "analyze_structure",
            _switch_evidence_source_scope,
            False,
            id="evidence-source-scope",
        ),
        pytest.param(
            "analyze_structure",
            "SummarySchemaGate@1",
            "analyze_contribution",
            lambda output: output["three_minute_read"].__setitem__("core_idea", ""),
            False,
            id="summary-schema",
        ),
        pytest.param(
            "analyze_contribution",
            "SummaryEvidenceCoverageGate@1",
            "analyze_experiments",
            lambda output: output.__setitem__("summary_evidence_refs", []),
            False,
            id="summary-evidence",
        ),
        pytest.param(
            "analyze_contribution",
            "SummaryEvidenceCoverageGate@1",
            "analyze_experiments",
            _switch_summary_evidence_scope,
            False,
            id="summary-evidence-scope",
        ),
        pytest.param(
            "analyze_experiments",
            "BenchmarkEvidenceLineageGate@1",
            "verify_claims",
            lambda output: output["scores"][0].__setitem__("source_refs", []),
            False,
            id="benchmark-lineage",
        ),
        pytest.param(
            "analyze_experiments",
            "BenchmarkEvidenceLineageGate@1",
            "verify_claims",
            lambda output: output["scores"][0].__setitem__("paper_id", "other-paper"),
            False,
            id="benchmark-paper-scope",
        ),
        pytest.param(
            "analyze_experiments",
            "BenchmarkEvidenceLineageGate@1",
            "verify_claims",
            lambda output: output["scores"][0].__setitem__(
                "source_refs", ["source://other-paper"]
            ),
            False,
            id="benchmark-source-scope",
        ),
        pytest.param(
            "verify_claims",
            "ClaimEvidenceGate@1",
            "quality_gate",
            lambda output: output["claim_models"][0].__setitem__("evidence_ids", []),
            False,
            id="claim-evidence",
        ),
        pytest.param(
            "quality_gate",
            "ResearchQualityGate@1",
            "build_reader_payload",
            lambda output: output["research_quality"].__setitem__("score", 0.5),
            False,
            id="research-quality",
        ),
        pytest.param(
            "quality_gate",
            "ResearchQualityGate@1",
            "build_reader_payload",
            _switch_quality_scope,
            False,
            id="research-quality-run-scope",
        ),
        pytest.param(
            "build_reader_payload",
            "ReaderPayloadSchemaGate@1",
            "build_paper_card",
            lambda output: output["reader_payload"].__setitem__("navigation", []),
            False,
            id="reader-payload-schema",
        ),
        pytest.param(
            "build_reader_payload",
            "ReaderPayloadSchemaGate@1",
            "build_paper_card",
            _switch_reader_scope,
            False,
            id="reader-payload-run-scope",
        ),
        pytest.param(
            "build_paper_card",
            "ResearchPaperCardGate@1",
            "publish_artifacts",
            lambda output: output["paper_card"].__setitem__("title", ""),
            False,
            id="paper-card",
        ),
        pytest.param(
            "build_paper_card",
            "ResearchPaperCardGate@1",
            "publish_artifacts",
            _switch_paper_card_scope,
            False,
            id="paper-card-run-scope",
        ),
    ),
)
def test_active_paper_gate_failure_records_exact_evidence_before_downstream_work(
    step_id: str,
    gate_reference: str,
    next_step_id: str,
    mutator: _OutputMutator,
    uses_controlled_repair: bool,
) -> None:
    artifact_port = FakeArtifactPort()
    event_port = InMemoryHarnessEventPort()
    runtime = _MutatingResearchSinglePaperRuntime(
        mutate_step_id=step_id,
        mutator=mutator,
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=artifact_port,
        event_port_factory=lambda run_id: event_port,
    )

    result = AnalyzePaperUseCase(runtime).analyze(
        AnalyzePaperRequest(
            run_id=f"gate-failure-{step_id}",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            options={"max_replans": 0},
        )
    )

    events = [event.to_dict() for event in result.trace.events]
    gate_id = gate_reference.rsplit("@", maxsplit=1)[0]
    failure_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "gate_evaluated"
        and event.get("step_id") == step_id
        and event.get("payload", {}).get("gate") == gate_id
        and event.get("payload", {}).get("passed") is False
    ]

    assert len(failure_indexes) == 1
    failure_event = events[failure_indexes[0]]
    evidence = failure_event["payload"]["details"]["harness_gate"]
    assert evidence["reference"] == gate_reference
    assert _CHECKSUM_PATTERN.fullmatch(evidence["input_ref"])
    assert _CHECKSUM_PATTERN.fullmatch(evidence["result_ref"])

    downstream_call_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "worker_called"
        and event.get("step_id") == next_step_id
    ]
    if uses_controlled_repair:
        assert downstream_call_indexes
        assert failure_indexes[0] < downstream_call_indexes[0]
    else:
        assert downstream_call_indexes == []
        assert result.status == "halted"

    if not uses_controlled_repair:
        assert artifact_port.storage == {}
        committed_history = event_port.read_history(result.run_id)
        assert committed_history
        assert any(
            event.event_type.value == "gate_evaluated"
            and event.step_id == step_id
            and event.payload.get("details", {})
            .get("harness_gate", {})
            .get("reference")
            == gate_reference
            for event in committed_history
        )


class _MutatingResearchSinglePaperRuntime(ResearchSinglePaperRuntime):
    def __init__(
        self,
        *,
        mutate_step_id: str,
        mutator: _OutputMutator,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._mutate_step_id = mutate_step_id
        self._mutator = mutator

    def _worker_registry(self, workspace):
        registry = super()._worker_registry(workspace)
        worker = registry[self._mutate_step_id]

        def mutate_output(task: dict[str, Any]) -> HarnessWorkerResult:
            result = worker(task)
            if result.status != HarnessWorkerStatus.SUCCEEDED:
                return result
            output = deepcopy(result.output)
            self._mutator(output)
            return HarnessWorkerResult(
                status=result.status,
                output=output,
                artifacts=result.artifacts,
                diagnostics=result.diagnostics,
                metrics=result.metrics,
                error=result.error,
            )

        registry[self._mutate_step_id] = mutate_output
        return registry
