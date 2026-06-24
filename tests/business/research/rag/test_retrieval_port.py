from __future__ import annotations

from dataclasses import dataclass

from framework.harness.retrieval.request import RetrievalRequest

from business.research.document.models import PaperChunk
from business.research.rag.retrieval_port import PaperChunkRetrievalPort
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
    assert "OCR Text:" in figure_pack.summary
