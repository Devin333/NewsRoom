from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.research.domain import (
    EvidenceRef,
    GateResult,
    ResearchAnalysis,
    ResearchDocument,
    ResearchPaper,
    ResearchQualityResult,
    ResearchReaderPayload,
    ResearchSection,
    SourceLineage,
    ThreeMinuteRead,
)
from business.research.reader import ReaderPayloadBuilder
from business.research.services import ResearchEvidenceBuilder
from tests.business.research.helpers import FIXED_NOW


@dataclass(frozen=True)
class FakeResearchAnalysisResult:
    run_id: str
    status: str
    analysis: ResearchAnalysis | None
    quality: ResearchQualityResult | None
    reader_payload: Any | None
    artifact_refs: dict[str, str]
    trace: dict[str, Any] = field(default_factory=dict)
    transcript: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    actor_scope: dict[str, str] = field(
        default_factory=lambda: {"memory_namespace": "research.public"}
    )

    @property
    def trace_ref(self) -> str:
        return f"harness-trace://{self.run_id}"

    @property
    def reader_payload_ref(self) -> str | None:
        return self.artifact_refs.get("research-reader-payload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "quality": self.quality.to_dict() if self.quality else None,
            "reader_payload": self.reader_payload.to_dict() if self.reader_payload else None,
            "artifact_refs": dict(self.artifact_refs),
            "trace": dict(self.trace),
            "transcript": dict(self.transcript),
            "diagnostics": dict(self.diagnostics),
            "actor_scope": dict(self.actor_scope),
            "trace_ref": self.trace_ref,
            "reader_payload_ref": self.reader_payload_ref,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FakeResearchAnalysisResult":
        analysis = value.get("analysis")
        quality = value.get("quality")
        reader_payload = value.get("reader_payload")
        return cls(
            run_id=str(value["run_id"]),
            status=str(value["status"]),
            analysis=(
                ResearchAnalysis.model_validate(analysis)
                if analysis is not None
                else None
            ),
            quality=(
                ResearchQualityResult.model_validate(quality)
                if quality is not None
                else None
            ),
            reader_payload=(
                ResearchReaderPayload.model_validate(reader_payload)
                if reader_payload is not None
                else None
            ),
            artifact_refs=dict(value.get("artifact_refs") or {}),
            trace=dict(value.get("trace") or {}),
            transcript=dict(value.get("transcript") or {}),
            diagnostics=dict(value.get("diagnostics") or {}),
            actor_scope=dict(value.get("actor_scope") or {}),
        )


class FakeAnalyzeUseCase:
    def __init__(self, result: FakeResearchAnalysisResult | None = None) -> None:
        self.result = result or make_research_result()
        self.calls = []

    def analyze(self, request):
        self.calls.append(request)
        scope = {
            "memory_namespace": request.memory_namespace or "research.public",
        }
        if request.tenant_id:
            scope["tenant_id"] = request.tenant_id
        if request.user_id:
            scope["user_id"] = request.user_id
        if isinstance(self.result.actor_scope, dict):
            self.result.actor_scope.clear()
            self.result.actor_scope.update(scope)
        if isinstance(self.result.trace, dict):
            self.result.trace["metadata"] = dict(scope)
        if isinstance(self.result.transcript, dict):
            for entry in self.result.transcript.get("entries", []):
                if isinstance(entry, dict):
                    entry["metadata"] = dict(scope)
        return self.result


def make_research_result(
    *,
    run_id: str = "research-run-1",
    paper_id: str = "paper-1",
    status: str = "succeeded",
    quality_passed: bool = True,
) -> FakeResearchAnalysisResult:
    paper = ResearchPaper(
        paper_id=paper_id,
        title="Harnessed Research Agents",
        authors=["Ada Lovelace", "Grace Hopper"],
        abstract="A paper about controlled research agents.",
        published_at=FIXED_NOW,
        source="arxiv",
        source_url="https://arxiv.org/abs/2606.00001",
        pdf_url="https://arxiv.org/pdf/2606.00001",
        code_url="https://github.com/newsroom/harnessed-research",
        topics=["agents", "research"],
    )
    document = ResearchDocument(
        paper_id=paper_id,
        source_hash="sha256-paper-1",
        sections=[
            ResearchSection(
                section_id="sec-intro",
                title="Introduction",
                level=1,
                text="Harness owns routing, gates, memory writes, and publication.",
                source_ref=f"paper://{paper_id}/sec-intro",
            )
        ],
        lineage=SourceLineage(source_refs=[f"paper://{paper_id}/sec-intro"], source_hash="sha256-paper-1"),
    )
    evidence = ResearchEvidenceBuilder().build_from_document(document=document)
    summary = ThreeMinuteRead(
        problem="Research agents need deterministic control.",
        core_idea="Separate Harness routing from LLM candidate generation.",
        key_contributions=["Bounded RAG", "Deterministic gates"],
        method_summary="A controlled PLAN EXECUTE VERIFY runtime.",
        experiment_summary="Evaluated with fake workers.",
        limitations=["Single-paper loop first"],
        why_it_matters="It keeps research outputs auditable.",
        read_next=["Reader repair memory"],
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence.evidence_ids[0],
                source_ref=f"paper://{paper_id}/sec-intro",
                section_id="sec-intro",
                confidence=1.0,
            )
        ],
        confidence=0.91,
    )
    analysis = ResearchAnalysis(
        paper_id=paper_id,
        summary=summary,
        contributions=["Bounded RAG"],
        methods=["harness"],
        experiments=["Fake worker evaluation"],
        limitations=["Single-paper loop first"],
        claims=[],
        evidence_pack_id=evidence.pack_id,
    )
    gate = GateResult.pass_("ResearchReportReadinessGate") if quality_passed else GateResult.fail(
        "ResearchReportReadinessGate",
        "analysis requires claims",
    )
    quality = ResearchQualityResult(
        result_id="quality-1",
        target_id=paper_id,
        target_type="summary",
        passed=quality_passed,
        score=1.0 if quality_passed else 0.4,
        gate_results=[gate],
    )
    reader_payload = ReaderPayloadBuilder().build(
        paper=paper,
        document=document,
        analysis=analysis,
        evidence=evidence,
    )
    return FakeResearchAnalysisResult(
        run_id=run_id,
        status=status,
        analysis=analysis,
        quality=quality,
        reader_payload=reader_payload,
        artifact_refs={
            "research-analysis": f"artifact://{run_id}/analysis",
            "research-reader-payload": f"artifact://{run_id}/reader",
            "research-quality-result": f"artifact://{run_id}/quality",
            "harness-trace": f"artifact://{run_id}/trace",
            "harness-transcript": f"artifact://{run_id}/transcript",
        },
        trace={
            "run_id": run_id,
            "metadata": {"memory_namespace": "research.public"},
            "events": [{"event_type": "phase_started"}],
        },
        transcript={
            "run_id": run_id,
            "entries": [
                {
                    "phase": "PLAN",
                    "metadata": {"memory_namespace": "research.public"},
                }
            ],
        },
        diagnostics={"gate_failures": [] if quality_passed else [gate.to_dict()]},
        actor_scope={"memory_namespace": "research.public"},
    )


__all__ = ["FakeAnalyzeUseCase", "FakeResearchAnalysisResult", "make_research_result"]
