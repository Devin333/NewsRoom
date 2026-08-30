from __future__ import annotations

from dataclasses import dataclass, field

from framework.harness import BoundedRAGSessionController, RAGBudget, RAGSessionStatus

from backend.research.document.models import PaperChunk
from backend.research.graphs import build_paper_analysis_context_graph_identity
from backend.research.rag.models import ResearchRetrievalGoal
from backend.research.rag.retrieval.paper_retriever import RetrievalResult
from backend.research.rag.retrieval_port import PaperChunkRetrievalPort
from backend.research.services.rag_policy import ResearchRAGPolicyBuilder


@dataclass
class _MethodOnlyRetriever:
    calls: list[object] = field(default_factory=list)

    def retrieve(self, request) -> RetrievalResult:
        self.calls.append(request)
        return RetrievalResult(
            child_chunks=[_method_chunk(request.paper_id)],
            parent_chunks=[],
            ref_chunks=[],
            intent="concept_method",
        )


def test_method_only_evidence_does_not_satisfy_required_experiment_type() -> None:
    paper_retriever = _MethodOnlyRetriever()
    retrieval = PaperChunkRetrievalPort(paper_retriever, default_section_index=1)  # type: ignore[arg-type]
    spec = ResearchRAGPolicyBuilder().build_session_spec(
        graph_identity=build_paper_analysis_context_graph_identity(
            run_id="run-evidence-convergence",
            stage_id="run_research_rag",
        ),
        session_id="session-evidence-convergence",
        goal=ResearchRetrievalGoal(
            goal_id="goal-evidence-convergence",
            paper_id="paper-convergence",
            question="What experiment result proves the model improves accuracy?",
            required_evidence_types=["experiment"],
            allowed_source_refs=["arxiv://paper-convergence/latex"],
            allowed_memory_namespaces=["research.reader_repair"],
        ),
        budget=RAGBudget(
            max_rounds=1,
            max_replans=0,
            max_queries=2,
            max_source_reads=0,
            max_memory_hits=1,
            max_context_items=4,
            max_context_tokens=1024,
            max_worker_calls=4,
        ),
    )

    result = BoundedRAGSessionController(retrieval=retrieval).run(spec)

    assert result.status == RAGSessionStatus.INSUFFICIENT_EVIDENCE
    assert result.context_pack is None
    assert result.decision.metadata["gap_report"]["missing_evidence_types"] == ["experiment"]
    assert result.decision.metadata["gap_report"]["accepted_evidence_ids"] == ["method-only-1"]
    source_event = next(
        event for event in result.transcript.events
        if event["event_type"] == "rag_source_verified"
    )
    assert source_event["payload"]["accepted"][0]["evidence_type"] == "method"
    assert source_event["payload"]["accepted"][0]["metadata"]["evidence_type_source"] == "content_resolved"
    assert [call.current_section_index for call in paper_retriever.calls] == [1]


def _method_chunk(paper_id: str) -> PaperChunk:
    return PaperChunk(
        chunk_id="method-only-1",
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content="The method describes the architecture but reports no experiment result.",
        metadata={
            "source_ref": f"arxiv://{paper_id}/method-only-1",
            "source_locator": f"paper://{paper_id}/pdf#page=2",
            "child_final_score": 0.91,
        },
    )
