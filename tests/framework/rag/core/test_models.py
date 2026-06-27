from __future__ import annotations

from framework.rag.core import (
    RAGChunk,
    RAGChunkStorePort,
    RAGContextAssemblerPort,
    RAGEvidence,
    RAGQuery,
    RAGRerankerPort,
    RAGRetrieverPort,
    RAGScoreBreakdown,
    SourceLocator,
)


def test_rag_core_models_serialize_generic_contracts():
    locator = SourceLocator(
        source_id="source://doc-1#page=2",
        page=2,
        bbox=(1, 2, 3, 4),
        section_path=("Methods",),
        span_start=10,
        span_end=20,
        raw_locator="source://doc-1#page=2",
        metadata={"kind": "section"},
    )
    chunk = RAGChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        text="The method uses retrieval.",
        chunk_type="paragraph",
        fields={"title": "Methods", "body": "The method uses retrieval."},
        source_locator=locator,
        metadata={"parent_chunk_id": "section-1"},
    )
    breakdown = RAGScoreBreakdown(
        child_similarity=0.8,
        field_score=0.4,
        final_score=0.7,
        extra={"custom_score": 0.3},
    )
    evidence = RAGEvidence(
        evidence_id="ev-1",
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        text=chunk.text,
        score=0.7,
        score_breakdown=breakdown,
        source_locator=locator,
        metadata={"reason": "matched"},
    )

    assert chunk.to_dict()["source_locator"]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert evidence.to_dict()["score_breakdown"] == {
        "child_similarity": 0.8,
        "field_score": 0.4,
        "final_score": 0.7,
        "custom_score": 0.3,
    }


def test_score_breakdown_from_mapping_omits_missing_or_non_numeric_values():
    breakdown = RAGScoreBreakdown.from_mapping({
        "child_similarity": "0.5",
        "parent_relevance": None,
        "field_score": "not-a-number",
        "final_score": 1,
        "custom_score": "0.25",
    })

    assert breakdown.to_dict() == {
        "child_similarity": 0.5,
        "final_score": 1.0,
        "custom_score": 0.25,
    }


def test_rag_core_ports_are_structural_protocols():
    query = RAGQuery(query="What does the method do?", intent="method", required_chunk_types=("paragraph",))
    chunk = RAGChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        text="Body text",
        chunk_type="paragraph",
    )
    evidence = RAGEvidence(
        evidence_id="chunk-1",
        chunk_id="chunk-1",
        document_id="doc-1",
        text="Body text",
    )

    class Store:
        def get_chunk(self, chunk_id: str) -> RAGChunk | None:
            return chunk if chunk_id == chunk.chunk_id else None

        def list_chunks(self, document_id: str):
            return [chunk] if document_id == chunk.document_id else []

    class Retriever:
        def retrieve(self, query: RAGQuery):
            return [evidence]

    class Reranker:
        def rerank(self, query: RAGQuery, evidence):
            return list(evidence)

    class Assembler:
        def assemble(self, query: RAGQuery, evidence):
            return list(evidence)

    assert isinstance(Store(), RAGChunkStorePort)
    assert isinstance(Retriever(), RAGRetrieverPort)
    assert isinstance(Reranker(), RAGRerankerPort)
    assert isinstance(Assembler(), RAGContextAssemblerPort)
    assert query.to_dict()["required_chunk_types"] == ["paragraph"]
