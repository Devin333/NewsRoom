from __future__ import annotations

from dataclasses import dataclass, field

from framework.harness import BoundedRAGSessionController, RAGBudget, RAGSessionStatus

from backend.research.document.models import PaperChunk
from backend.research.graphs import build_paper_analysis_context_graph_identity
from backend.research.rag.models import ResearchRetrievalGoal
from backend.research.rag.retrieval_port import PaperChunkRetrievalPort
from backend.research.rag.retrieval.paper_retriever import RetrievalResult
from backend.research.services.rag_policy import ResearchRAGPolicyBuilder


@dataclass
class _PaperRetriever:
    calls: list[object] = field(default_factory=list)

    def retrieve(self, request) -> RetrievalResult:
        self.calls.append(request)
        if len(self.calls) == 1:
            return RetrievalResult(
                child_chunks=[_method_chunk(request.paper_id, request.current_section_index)],
                parent_chunks=[],
                ref_chunks=[],
                intent="concept_method",
            )
        return RetrievalResult(
            child_chunks=[_figure_chunk(request.paper_id, request.current_section_index)],
            parent_chunks=[],
            ref_chunks=[],
            intent="figure_query",
        )


def test_paper_rag_runs_through_harness_kernel_retriever_to_context_pack() -> None:
    paper_retriever = _PaperRetriever()
    retrieval = PaperChunkRetrievalPort(paper_retriever, default_section_index=2)  # type: ignore[arg-type]
    spec = ResearchRAGPolicyBuilder().build_session_spec(
        graph_identity=build_paper_analysis_context_graph_identity(
            run_id="run-paper-rag-kernel",
            stage_id="run_research_rag",
        ),
        session_id="session-paper-rag-kernel",
        goal=ResearchRetrievalGoal(
            goal_id="goal-paper-rag-kernel",
            paper_id="1706.03762",
            question="How does the Transformer method work, and what figure shows it?",
            required_evidence_types=["method", "figure"],
            target_sections=["method"],
            allowed_source_refs=["arxiv://1706.03762/latex"],
            allowed_memory_namespaces=["research.reader_repair"],
        ),
        budget=RAGBudget(
            max_rounds=2,
            max_replans=1,
            max_queries=4,
            max_source_reads=0,
            max_memory_hits=4,
            max_context_items=4,
            max_context_tokens=2048,
            max_worker_calls=8,
        ),
    )

    result = BoundedRAGSessionController(retrieval=retrieval).run(spec)

    assert result.status == RAGSessionStatus.SUCCEEDED
    assert result.context_pack is not None
    assert [call.current_section_index for call in paper_retriever.calls] == [2, 2]

    accepted = result.context_pack.accepted_evidence
    assert [item.evidence_id for item in accepted] == ["method-1", "figure-1"]
    assert [item.evidence_type for item in accepted] == ["method", "figure"]
    assert accepted[0].metadata["rag_document_id"] == "1706.03762"
    assert accepted[0].metadata["rag_chunk_id"] == "method-1"
    assert accepted[0].metadata["rag_source_locator"]["page"] == 3
    assert accepted[1].metadata["image_ref"] == "figures/figure-1.png"

    trace = result.context_pack.evidence_trace
    assert [item["evidence_id"] for item in trace] == ["method-1", "figure-1"]
    assert [item["evidence_type"] for item in trace] == ["method", "figure"]
    assert all(item["source_ref"].startswith("paper://1706.03762/pdf") for item in trace)
    assert all(item["artifact_refs"] for item in trace)
    assert any(ref.startswith("rag-kernel://retrieval/") for ref in result.context_pack.artifact_refs)

    event_types = [event["event_type"] for event in result.transcript.events]
    assert "rag_plan_candidate_created" in event_types
    assert "rag_context_pack_assembled" in event_types
    assert "rag_context_pack_returned" in event_types


def _method_chunk(paper_id: str, section_index: int) -> PaperChunk:
    return PaperChunk(
        chunk_id="method-1",
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Model Architecture",
        section_role=["method"],
        section_index=section_index,
        content="The Transformer uses stacked self-attention and feed-forward layers.",
        metadata={
            "source_ref": f"arxiv://{paper_id}/method-1",
            "source_locator": f"paper://{paper_id}/pdf#page=3&pdf_rect=10,20,300,140",
            "page": 3,
            "pdf_rect": [10, 20, 300, 140],
            "child_final_score": 0.91,
            "field_score": 0.82,
        },
    )


def _figure_chunk(paper_id: str, section_index: int) -> PaperChunk:
    return PaperChunk(
        chunk_id="figure-1",
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="figure",
        parent_chunk_id="method-1",
        section_title="Model Architecture",
        section_role=["method"],
        section_index=section_index,
        has_figure=True,
        figure_id="fig1",
        content="[Figure fig1]\nCaption:\nThe Transformer model architecture.",
        metadata={
            "source_ref": f"arxiv://{paper_id}/figure-1",
            "source_locator": f"paper://{paper_id}/pdf#page=3&pdf_rect=30,160,420,520",
            "page": 3,
            "pdf_rect": [30, 160, 420, 520],
            "image_ref": "figures/figure-1.png",
            "caption_text": "The Transformer model architecture.",
            "caption_source_locator": f"paper://{paper_id}/pdf#page=3&pdf_rect=30,525,420,560",
            "fused_score": 0.88,
            "visual_score": 0.93,
            "text_score": 0.78,
        },
    )
