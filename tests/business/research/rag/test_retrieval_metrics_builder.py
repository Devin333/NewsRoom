from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.rag.retrieval.metrics import RetrievalMetricsBuilder
from business.research.rag.retrieval.paper_claim_index import ClaimRecord, ClaimSearchHit
from business.research.rag.retrieval.paper_policy import RetrievalRoute
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy
from business.research.rag.retrieval.trace import RetrievalDegradation, RetrievalTrace


def _chunk(chunk_id: str, *, metadata: dict[str, Any] | None = None) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Results",
        section_role=["experiment"],
        section_index=2,
        content="The result improves accuracy.",
        metadata=metadata or {},
    )


def _claim_hit(chunk_id: str = "para-1") -> ClaimSearchHit:
    return ClaimSearchHit(
        record=ClaimRecord(
            claim_id="claim-1",
            paper_id="p1",
            chunk_id=chunk_id,
            section_title="Results",
            claim_text="The model improves accuracy.",
            source_locator="paper://p1#page=2",
            claim_type="result",
        ),
        score=0.9,
    )


@dataclass(frozen=True)
class _RecallResult:
    query_variants: list[str]


class _Plan:
    candidate_filter_groups = ()
    element_query_labels = ("1",)

    def route_dict(self) -> dict[str, Any]:
        return {"intent": "figure_query"}

    def to_dict(self) -> dict[str, Any]:
        return {"channels": ["dense_text"]}


def test_retrieval_metrics_builder_preserves_core_metadata() -> None:
    policy = RetrievalPolicy(name="unit", hybrid_rrf_enabled=True, field_reranking_enabled=True)
    trace = RetrievalTrace(policy_name="unit", policy_hash="hash", route={"intent": "figure_query"})
    trace.append_degradation_once(RetrievalDegradation(
        code="sparse_bm25_index_missing",
        stage="sparse_lexical",
        paper_id="p1",
        reason="missing index",
    ))
    child = _chunk(
        "para-1",
        metadata={
            "sparse_lexical_hit": True,
            "hybrid_rrf_fusion": True,
            "field_score": 0.7,
            "field_embedding_score": 0.8,
            "field_rerank_score": 0.9,
            "best_matching_field": "caption",
            "expansion_reason": "figure_nearby_context",
        },
    )

    metrics = RetrievalMetricsBuilder(
        policy=policy,
        reranker_available=True,
        field_index_available=True,
        field_reranker_available=True,
        visual_store_available=True,
        claim_index_available=True,
    ).build(
        active_policy_hash="hash",
        plan=_Plan(),
        route=RetrievalRoute(intent="figure_query", recall_routes=("figure_chunks",)),
        candidate_filters=[{"chunk_type": "figure"}],
        candidate_limit=5,
        recall_result=_RecallResult(query_variants=["figure query"]),
        candidates=[(child, 0.88)],
        field_hits=[
            FieldEmbeddingHit(
                chunk_id="para-1",
                field_name="caption",
                score=0.8,
                field_text="caption",
            )
        ],
        claim_hits=[_claim_hit()],
        n_recalled=1,
        n_visual_recalled=1,
        base_reranker_enabled=True,
        field_reranker_enabled=True,
        n_filtered=0,
        scored=[(child, 0.77)],
        child_chunks=[child],
        parent_chunks=[_chunk("parent")],
        ref_chunks=[],
        supplemental_table_chunks=[],
        table_context_chunks=[],
        top_score=0.77,
        elapsed_ms=12.3,
        retrieval_trace=trace,
        parent_metrics={"parent_scoring_enabled": True},
    )

    assert metrics["retrieval_policy"] == "unit"
    assert metrics["retrieval_policy_config_hash"] == "hash"
    assert metrics["field_hits_by_name"] == {"caption": 1}
    assert metrics["claim_index_top_claim_ids"] == ["claim-1"]
    assert metrics["sparse_recalled"] == 1
    assert metrics["hybrid_rrf_recalled"] == 1
    assert metrics["figure_context_returned"] == 1
    assert metrics["field_score_top"] == 0.7
    assert metrics["field_embedding_score_top"] == 0.8
    assert metrics["field_rerank_top"] == 0.9
    assert metrics["best_matching_fields"] == {"caption": 1}
    assert metrics["retrieval_trace"]["degradations"] == metrics["retrieval_degradations"]
    assert metrics["parent_scoring_enabled"] is True
