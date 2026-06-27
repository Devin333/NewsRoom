from __future__ import annotations

from dataclasses import dataclass

from framework.harness.retrieval.request import RetrievalRequest
from framework.rag.core import RAGQuery

from business.research.document.citation_spans import build_paragraph_span_metadata
from business.research.document.models import PaperChunk
from business.research.rag.retrieval_port import PaperChunkRetrievalPort, PaperKernelRAGRetriever
from business.research.rag.retriever import RetrievalResult


@dataclass
class _SpyRetriever:
    """Records the section_index it was asked to retrieve with."""
    seen_section_index: int | None = None
    result: RetrievalResult | None = None

    def retrieve(self, request) -> RetrievalResult:
        self.seen_section_index = request.current_section_index
        if self.result is not None:
            return self.result
        chunk = PaperChunk(
            chunk_id="c1",
            paper_id=request.paper_id,
            parse_source="latex",
            chunk_type="paragraph",
            section_title="Method",
            section_role=["method"],
            section_index=request.current_section_index,
            content="content",
            metadata={"source_ref": f"arxiv://{request.paper_id}/c1"},
        )
        return RetrievalResult(parent_chunks=[chunk], child_chunks=[chunk], ref_chunks=[], intent="concept_method")


def _request(metadata: dict | None = None) -> RetrievalRequest:
    return RetrievalRequest(
        query="how does attention work",
        scope="default",
        context_refs=("arxiv://1706.03762/latex",),
        limit=5,
        metadata=metadata or {},
    )


def test_request_metadata_takes_precedence():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=2)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": 7}))
    assert spy.seen_section_index == 7


def test_falls_back_to_default_when_metadata_absent():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=4)  # type: ignore[arg-type]
    port.retrieve(_request({}))
    assert spy.seen_section_index == 4


def test_invalid_metadata_falls_back_to_default():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=3)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": "bad"}))
    assert spy.seen_section_index == 3


def test_negative_metadata_falls_back_to_default():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=6)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": -1}))
    assert spy.seen_section_index == 6


def test_default_zero_when_nothing_provided():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    port.retrieve(_request({}))
    assert spy.seen_section_index == 0


def test_paper_id_extracted_from_context_refs():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))
    assert result.packs
    assert result.packs[0].lineage == ("1706.03762",)


def test_section_index_echoed_in_collection_metadata():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=5)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))
    assert result.metadata["section_index"] == 5
    assert result.metadata["adapter"] == "kernel_rag_retriever_harness_adapter"
    assert result.request_ref == "rag-kernel://retrieval/paper_query/how-does-attention-work"


def test_paper_kernel_rag_retriever_projects_chunks_to_rag_evidence():
    spy = _SpyRetriever()
    retriever = PaperKernelRAGRetriever(spy, default_section_index=5)  # type: ignore[arg-type]

    evidence = retriever.retrieve(RAGQuery(
        query="how does attention work",
        intent="paper_query",
        filters={"context_refs": ["arxiv://1706.03762/latex"]},
        limit=2,
    ))

    assert spy.seen_section_index == 5
    assert [item.evidence_id for item in evidence] == ["c1"]
    assert evidence[0].chunk_id == "c1"
    assert evidence[0].document_id == "1706.03762"
    assert evidence[0].metadata["chunk_type"] == "paragraph"
    assert evidence[0].source_locator is not None
    assert retriever.last_metadata["intent"] == "concept_method"
    assert retriever.last_metadata["section_index"] == 5


def test_parent_context_metadata_exposed_in_evidence_pack():
    parent = PaperChunk(
        chunk_id="sec-method",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=2,
        content="Snippet around a matched child.",
        metadata={
            "source_ref": "arxiv://1706.03762/sec-method",
            "parent_expansion_reason": "child_parent_context",
            "parent_anchor_child_id": "para-method",
            "parent_snippet": True,
            "parent_snippet_strategy": "child_anchor_window",
            "source_parent_chunk_id": "sec-method",
            "parent_rerank_score": 0.91,
            "parent_rerank_strategy": "cross_encoder",
            "parent_child_relevance_score": 0.8,
            "parent_relevance_score": 0.91,
            "parent_section_heading_score": 1.0,
            "parent_position_score": 0.7,
            "parent_final_score": 0.875,
            "parent_score_strategy": "cross_encoder",
            "parent_score_weights": {
                "child": 0.4,
                "parent": 0.3,
                "heading": 0.2,
                "position": 0.1,
            },
            "title_score": 0.6,
            "abstract_score": 0.0,
            "caption_score": 0.0,
            "equation_score": 0.0,
            "body_score": 0.4,
            "field_score": 0.52,
            "field_score_weights": {
                "title": 0.35,
                "abstract": 0.15,
                "caption": 0.1,
                "equation": 0.1,
                "body": 0.3,
            },
            "field_score_strategy": "lexical_overlap",
            "title_embedding_score": 0.72,
            "abstract_embedding_score": 0.0,
            "caption_embedding_score": 0.0,
            "equation_embedding_score": 0.0,
            "body_embedding_score": 0.4,
            "field_embedding_score": 0.72,
            "field_embedding_scores": {"title": 0.72, "body": 0.4},
            "field_embedding_hits": [{"field_name": "title", "score": 0.72}],
            "best_embedding_field": "title",
            "field_embedding_strategy": "field_vector_search",
            "field_rerank_score": 0.88,
            "field_rerank_strategy": "cross_encoder_structured_fields",
            "best_matching_field": "title",
            "element_label_boost": 0.18,
            "graph_score": 0.6,
            "child_score_strategy": "semantic_field_embedding_rerank_fusion",
            "child_score_components": {
                "semantic": 0.8,
                "deterministic_field": 0.52,
                "field_embedding": 0.72,
                "field_rerank": 0.88,
                "position": 0.7,
                "graph": 0.6,
            },
            "field_text_available_fields": ("title", "body"),
            "field_text_sources": {"title": ("section_title",), "body": ("content",)},
            "child_semantic_score": 0.8,
            "child_position_score": 0.7,
            "child_final_score": 0.739,
            "child_score_weights": {
                "semantic": 0.75,
                "field": 0.2,
                "position": 0.05,
            },
        },
    )
    spy = _SpyRetriever(result=RetrievalResult(
        child_chunks=[],
        parent_chunks=[parent],
        ref_chunks=[],
        intent="concept_method",
    ))

    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))

    pack = result.packs[0]
    assert pack.metadata["parent_expansion_reason"] == "child_parent_context"
    assert pack.metadata["parent_anchor_child_id"] == "para-method"
    assert pack.metadata["parent_snippet"] is True
    assert pack.metadata["parent_snippet_strategy"] == "child_anchor_window"
    assert pack.metadata["source_parent_chunk_id"] == "sec-method"
    assert pack.metadata["parent_rerank_score"] == 0.91
    assert pack.metadata["parent_rerank_strategy"] == "cross_encoder"
    assert pack.metadata["parent_child_relevance_score"] == 0.8
    assert pack.metadata["parent_relevance_score"] == 0.91
    assert pack.metadata["parent_section_heading_score"] == 1.0
    assert pack.metadata["parent_position_score"] == 0.7
    assert pack.metadata["parent_final_score"] == 0.875
    assert pack.metadata["parent_score_strategy"] == "cross_encoder"
    assert pack.metadata["parent_score_weights"]["heading"] == 0.2
    assert pack.metadata["title_score"] == 0.6
    assert pack.metadata["field_score"] == 0.52
    assert pack.metadata["field_score_strategy"] == "lexical_overlap"
    assert pack.metadata["field_score_weights"]["title"] == 0.35
    assert pack.metadata["title_embedding_score"] == 0.72
    assert pack.metadata["field_embedding_score"] == 0.72
    assert pack.metadata["field_embedding_scores"]["title"] == 0.72
    assert pack.metadata["field_embedding_hits"][0]["field_name"] == "title"
    assert pack.metadata["best_embedding_field"] == "title"
    assert pack.metadata["field_embedding_strategy"] == "field_vector_search"
    assert pack.metadata["field_rerank_score"] == 0.88
    assert pack.metadata["field_rerank_strategy"] == "cross_encoder_structured_fields"
    assert pack.metadata["best_matching_field"] == "title"
    assert pack.metadata["element_label_boost"] == 0.18
    assert pack.metadata["graph_score"] == 0.6
    assert pack.metadata["child_score_strategy"] == "semantic_field_embedding_rerank_fusion"
    assert pack.metadata["child_score_components"]["field_rerank"] == 0.88
    assert pack.metadata["field_text_available_fields"] == ("title", "body")
    assert pack.metadata["field_text_sources"]["title"] == ("section_title",)
    assert pack.metadata["child_semantic_score"] == 0.8
    assert pack.metadata["child_position_score"] == 0.7
    assert pack.metadata["child_final_score"] == 0.739
    assert pack.metadata["child_score_weights"]["field"] == 0.2


def test_formula_child_is_emitted_as_evidence_before_parent_context():
    formula = PaperChunk(
        chunk_id="eq-1",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="formula",
        parent_chunk_id="para-1",
        section_title="Method",
        section_role=["method"],
        section_index=3,
        has_formula=True,
        formula_latex=r"\operatorname{Attention}(Q,K,V)",
        content=(
            "[Equation eq1]\n"
            "LaTeX:\n"
            r"\operatorname{Attention}(Q,K,V)" "\n\n"
            "Context:\n"
            "The paragraph explains scaled dot-product attention."
        ),
        metadata={
            "source_ref": "arxiv://1706.03762/eq-1",
            "source_locator": "paper://1706.03762/pdf#page=5&pdf_rect=10,20,30,40",
            "page": 5,
            "pdf_rect": [10, 20, 30, 40],
        },
    )
    parent = PaperChunk(
        chunk_id="para-1",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=3,
        has_formula=True,
        formula_latex=r"\operatorname{Attention}(Q,K,V)",
        content="The paragraph explains scaled dot-product attention.",
        metadata={"source_ref": "arxiv://1706.03762/para-1"},
    )
    spy = _SpyRetriever(result=RetrievalResult(
        child_chunks=[formula],
        parent_chunks=[parent],
        ref_chunks=[],
        intent="formula_query",
    ))

    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))

    assert [pack.evidence_id for pack in result.packs] == ["eq-1", "para-1"]
    formula_pack = result.packs[0]
    assert formula_pack.metadata["chunk_type"] == "formula"
    assert formula_pack.metadata["parent_chunk_id"] == "para-1"
    assert formula_pack.metadata["has_formula"] is True
    assert formula_pack.metadata["formula_latex"] == r"\operatorname{Attention}(Q,K,V)"
    assert formula_pack.metadata["page"] == 5
    assert formula_pack.metadata["pdf_rect"] == [10, 20, 30, 40]
    assert formula_pack.metadata["rag_document_id"] == "1706.03762"
    assert formula_pack.metadata["rag_chunk_id"] == "eq-1"
    assert formula_pack.metadata["rag_source_locator"]["page"] == 5
    assert formula_pack.metadata["rag_source_locator"]["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert "LaTeX:" in formula_pack.summary


def test_table_row_group_evidence_exposes_visual_metadata():
    row_group = PaperChunk(
        chunk_id="tbl-1-rows-20-39",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="table",
        parent_chunk_id="tbl-1",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=4,
        has_table=True,
        content="[Table tab1]\nRows:\nrow_range=20-39\nmodel | 93.2",
        metadata={
            "source_ref": "arxiv://1706.03762/tbl-1-rows-20-39",
            "source_locator": "paper://1706.03762/pdf#page=8&pdf_rect=10,20,300,400",
            "caption_source_locator": "paper://1706.03762/pdf#page=8&pdf_rect=10,5,300,18",
            "page": 8,
            "pdf_rect": [10, 20, 300, 400],
            "caption_pdf_rect": [10, 5, 300, 18],
            "image_ref": "tables/table1.png",
            "table_id": "tab1",
            "content_sources": ["caption", "columns", "rows", "nearby_context"],
            "row_start": 20,
            "row_end": 39,
            "parent_table_chunk_id": "tbl-1",
            "is_table_row_group": True,
        },
    )
    parent = PaperChunk(
        chunk_id="tbl-1",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="table",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=4,
        has_table=True,
        content="[Table tab1]\nCaption:\nMain results.",
        metadata={
            "source_ref": "arxiv://1706.03762/tbl-1",
            "table_id": "tab1",
        },
    )
    spy = _SpyRetriever(result=RetrievalResult(
        child_chunks=[row_group],
        parent_chunks=[parent],
        ref_chunks=[],
        intent="table_query",
    ))

    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))

    assert [pack.evidence_id for pack in result.packs] == ["tbl-1-rows-20-39", "tbl-1"]
    table_pack = result.packs[0]
    assert table_pack.metadata["chunk_type"] == "table"
    assert table_pack.metadata["has_table"] is True
    assert table_pack.metadata["table_id"] == "tab1"
    assert table_pack.metadata["image_ref"] == "tables/table1.png"
    assert table_pack.metadata["row_start"] == 20
    assert table_pack.metadata["row_end"] == 39
    assert table_pack.metadata["is_table_row_group"] is True
    assert table_pack.metadata["parent_table_chunk_id"] == "tbl-1"
    assert table_pack.metadata["caption_pdf_rect"] == [10, 5, 300, 18]


def test_paragraph_overlap_span_metadata_exposed_in_evidence_pack():
    content = "Borrowed sentence.\nCurrent body keeps the main content."
    child = PaperChunk(
        chunk_id="para-1",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="paragraph",
        parent_chunk_id="sec-method",
        section_title="Method",
        section_role=["method"],
        section_index=2,
        content=content,
        metadata={
            "source_ref": "arxiv://1706.03762/para-1",
            "source_locator": "paper://1706.03762/pdf#page=4",
            **build_paragraph_span_metadata(
                content=content,
                overlap_text="Borrowed sentence.",
                overlap_origin_chunk_id="para-0",
                overlap_origin_source_locator="paper://1706.03762/pdf#page=3",
            ),
        },
    )
    spy = _SpyRetriever(result=RetrievalResult(
        child_chunks=[child],
        parent_chunks=[],
        ref_chunks=[],
        intent="concept_method",
    ))

    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))

    assert [pack.evidence_id for pack in result.packs] == ["para-1"]
    pack = result.packs[0]
    assert pack.metadata["content_span_unit"] == "char_offset"
    assert pack.metadata["main_span"]["start"] > 0
    assert pack.metadata["main_span"]["end"] == len(content)
    assert pack.metadata["overlap_spans"] == [{
        "start": 0,
        "end": len("Borrowed sentence."),
        "origin_chunk_id": "para-0",
        "origin_source_locator": "paper://1706.03762/pdf#page=3",
        "overlap_type": "previous_paragraph_trailing_sentence",
    }]


def test_figure_evidence_exposes_ocr_diagnostics():
    figure = PaperChunk(
        chunk_id="fig-1",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="figure",
        parent_chunk_id="para-fig",
        section_title="Model Architecture",
        section_role=["method"],
        section_index=2,
        has_figure=True,
        figure_id="fig1",
        content="[Figure fig1]\nCaption:\nArchitecture.\n\nOCR Text:\nEncoder Decoder Attention",
        metadata={
            "source_ref": "arxiv://1706.03762/fig-1",
            "source_locator": "paper://1706.03762/pdf#page=3&pdf_rect=10,20,300,400",
            "image_ref": "figures/fig1.png",
            "ocr_attempted": True,
            "ocr_chars": 25,
            "ocr_text_source": "surya_ocr_crop",
            "content_sources": ["caption", "nearby_context", "ocr"],
            "text_score": 0.24,
            "visual_score": 0.91,
            "fused_score": 0.47,
            "fusion_strategy": "text_image_fusion",
            "visual_hit": True,
        },
    )
    parent = PaperChunk(
        chunk_id="para-fig",
        paper_id="1706.03762",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Model Architecture",
        section_role=["method"],
        section_index=2,
        content="The paragraph explains the architecture.",
        metadata={"source_ref": "arxiv://1706.03762/para-fig"},
    )
    spy = _SpyRetriever(result=RetrievalResult(
        child_chunks=[figure],
        parent_chunks=[parent],
        ref_chunks=[],
        intent="figure_query",
    ))

    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))

    figure_pack = result.packs[0]
    assert figure_pack.metadata["chunk_type"] == "figure"
    assert figure_pack.metadata["image_ref"] == "figures/fig1.png"
    assert figure_pack.metadata["ocr_attempted"] is True
    assert figure_pack.metadata["ocr_chars"] == 25
    assert figure_pack.metadata["ocr_text_source"] == "surya_ocr_crop"
    assert figure_pack.metadata["text_score"] == 0.24
    assert figure_pack.metadata["visual_score"] == 0.91
    assert figure_pack.metadata["fused_score"] == 0.47
    assert figure_pack.metadata["fusion_strategy"] == "text_image_fusion"
    assert figure_pack.metadata["visual_hit"] is True
    assert figure_pack.metadata["rag_score"] == 0.47
    assert figure_pack.metadata["rag_score_breakdown"] == {
        "final_score": 0.47,
        "text_score": 0.24,
        "visual_score": 0.91,
    }
    assert "OCR Text:" in figure_pack.summary
