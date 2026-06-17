from __future__ import annotations

import pytest

from business.research.document.chunker import PaperDocumentChunker
from business.research.document.models import PaperChunk
from business.research.document.section_detector import classify_section_role, is_abstract_section
from business.research.document.special_element_scanner import scan_special_elements
from business.research.rag.routing import build_retrieval_route, classify_query_intent
from tests.business.research.document.helpers import (
    make_doc,
    make_equation,
    make_figure,
    make_section,
    make_table,
)

CHUNKER = PaperDocumentChunker()


# ── section_detector ─────────────────────────────────────────────────────────

def test_is_abstract_section():
    assert is_abstract_section("Abstract")
    assert is_abstract_section("摘要")
    assert not is_abstract_section("Introduction")


@pytest.mark.parametrize("title,expected_role", [
    ("Experiments", "experiment"),
    ("Method", "method"),
    ("Related Work", "related_work"),
    ("Conclusion", "conclusion"),
    ("Introduction", "background"),
    ("Analysis", "analysis"),
])
def test_classify_section_role(title, expected_role):
    roles = classify_section_role(title)
    assert expected_role in roles


# ── special_element_scanner ───────────────────────────────────────────────────

def test_scan_figures_and_equations():
    doc = make_doc(sections=[
        make_section("s1", "Introduction", "As shown in 图 fig1, results are great.")
    ])
    doc2 = doc.model_copy(update={
        "figures": [make_figure("fig1", "Our proposed architecture.")],
        "equations": [make_equation("eq1", r"\mathcal{L} = \sum_i y_i \log \hat{y}_i")],
    })
    elements = scan_special_elements(doc2)
    assert "fig1" in elements.figures
    assert "eq1" in elements.equations


def test_scan_variable_definitions():
    doc = make_doc(sections=[
        make_section("s1", "Method", "Let α denotes learning rate, and β represents momentum.")
    ])
    elements = scan_special_elements(doc)
    assert "α" in elements.variable_definitions


# ── chunker ───────────────────────────────────────────────────────────────────

def _structured_doc():
    return make_doc(sections=[
        make_section("s0", "Abstract", "We propose a novel approach. It outperforms all baselines."),
        make_section("s1", "Introduction", "Background information.\n\nMore context here."),
        make_section("s2", "Method", "Our method uses attention.\n\nSpecifically, we apply $W_q$ to queries."),
        make_section("s3", "Experiments", "We evaluate on GLUE.\n\nResults show F1=92."),
        make_section("s4", "Conclusion", "We proposed a framework.\n\nFuture work remains."),
    ])


def test_chunk_produces_abstract_chunk():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "pymupdf")
    abstract_chunks = [c for c in chunks if c.chunk_type == "abstract"]
    assert len(abstract_chunks) == 1
    assert "novel approach" in abstract_chunks[0].content


def test_chunk_produces_parent_and_child():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "pymupdf")
    parents = [c for c in chunks if c.metadata.get("is_parent")]
    children = [c for c in chunks if c.parent_chunk_id is not None]
    assert parents, "expected section-level parent chunks"
    assert children, "expected paragraph-level child chunks"


def test_child_references_parent():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "pymupdf")
    parent_ids = {c.chunk_id for c in chunks if c.metadata.get("is_parent")}
    for child in [c for c in chunks if c.parent_chunk_id]:
        assert child.parent_chunk_id in parent_ids


def test_section_role_assigned():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "pymupdf")
    method_chunks = [c for c in chunks if "method" in c.section_role]
    assert method_chunks


def test_formula_detected_in_paragraph():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "latex")
    formula_chunks = [c for c in chunks if c.has_formula]
    assert formula_chunks, "expected at least one chunk with formula detected"


def test_overlap_applied():
    text = "First sentence ends here.\n\nSecond paragraph starts here and continues on."
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "Abstract text."),
        make_section("s1", "Introduction", text),
        make_section("s2", "Method", "Method A.\n\nMethod B."),
        make_section("s3", "Experiments", "Exp A.\n\nExp B."),
    ])
    chunks = CHUNKER.chunk(doc, "pymupdf")
    second_child = [
        c for c in chunks
        if not c.metadata.get("is_parent") and c.metadata.get("para_index") == 1
        and "Introduction" in c.section_title
    ]
    assert second_child
    # second paragraph should contain trailing sentence from first as overlap
    assert "First sentence ends here" in second_child[0].content


def test_figure_caption_embedded():
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "Abstract."),
        make_section("s1", "Introduction", "Intro."),
        make_section("s2", "Method", "As shown in Fig. 1, performance improves.\n\nMore details."),
        make_section("s3", "Experiments", "Experiment text."),
    ])
    doc2 = doc.model_copy(update={
        "figures": [make_figure("fig_1", "Performance improvement over baselines.")],
    })
    chunks = CHUNKER.chunk(doc2, "pymupdf")
    fig_ref_chunks = [c for c in chunks if c.has_figure]
    assert fig_ref_chunks


def test_table_chunk_produced():
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "Abstract."),
        make_section("s1", "Introduction", "Intro."),
        make_section("s2", "Experiments", "Results in table 1."),
        make_section("s3", "Conclusion", "Conclusion."),
    ])
    doc2 = doc.model_copy(update={
        "tables": [make_table("tab1", "Main results", ["Model", "F1"])],
    })
    chunks = CHUNKER.chunk(doc2, "pymupdf")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert table_chunks
    assert "tab1" in table_chunks[0].content


def test_fallback_for_unstructured_doc():
    # Only 2 non-abstract sections → triggers fallback
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "Abstract text."),
        make_section("s1", "Introduction", "Intro text."),
        make_section("s2", "Method", "Method text."),
    ])
    chunks = CHUNKER.chunk(doc, "pymupdf")
    assert all(not c.structure_detected for c in chunks)


def test_structure_detected_flag():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "pymupdf")
    assert all(c.structure_detected for c in chunks)


def test_parse_source_propagated():
    doc = _structured_doc()
    for source in ("latex", "marker", "pymupdf"):
        chunks = CHUNKER.chunk(doc, source)  # type: ignore[arg-type]
        assert all(c.parse_source == source for c in chunks)


def test_chunk_model_required_fields():
    with pytest.raises(Exception):
        PaperChunk(chunk_id="", paper_id="p1", parse_source="latex", content="text")

    with pytest.raises(Exception):
        PaperChunk(chunk_id="c1", paper_id="p1", parse_source="latex", content="")


# ── routing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,expected_intent", [
    ("图3说明了什么？", "figure_query"),
    ("What does Figure 3 show?", "figure_query"),
    ("这个公式的含义是什么？", "formula_query"),
    ("在GLUE基准上F1达到了多少？", "numerical_result"),
    ("这篇论文的主要贡献是什么？", "contribution"),
    ("与BERT相比性能如何？", "comparison"),
    ("作者的方法使用了什么架构？", "concept_method"),
])
def test_classify_query_intent(question, expected_intent):
    assert classify_query_intent(question) == expected_intent


def test_build_retrieval_route_figure():
    route = build_retrieval_route("图3展示了什么？")
    assert route.intent == "figure_query"
    assert "figure" in route.chunk_type_filter


def test_build_retrieval_route_method():
    route = build_retrieval_route("作者如何设计模型架构？")
    assert route.intent == "concept_method"
    assert "method" in route.section_role_filter


def test_build_retrieval_route_experiment():
    route = build_retrieval_route("在GLUE上准确率是多少？")
    assert route.intent == "numerical_result"
    assert route.use_propositions


# ── edge cases ─────────────────────────────────────────────────────────────────

def test_empty_document_produces_no_chunks():
    doc = make_doc(sections=[])
    chunks = CHUNKER.chunk(doc, "latex")
    assert chunks == []


def test_sections_with_blank_text_handled():
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "   "),
        make_section("s1", "Introduction", ""),
        make_section("s2", "Method", "Real method content here."),
        make_section("s3", "Experiments", "Real experiment content."),
    ])
    # should not raise; only non-empty sections yield content chunks
    chunks = CHUNKER.chunk(doc, "latex")
    assert all(c.content.strip() for c in chunks)


def test_long_unstructured_doc_triggers_token_fallback():
    long_text = " ".join(f"word{i}" for i in range(4000))
    doc = make_doc(sections=[
        make_section("s0", "Body", long_text),
        make_section("s1", "More", long_text),
    ])
    chunks = CHUNKER.chunk(doc, "pymupdf")
    assert chunks
    assert all(not c.structure_detected for c in chunks)
    # fallback splits into multiple fixed-window chunks
    assert len(chunks) > 1


def test_cross_section_reference_recorded():
    doc = make_doc(sections=[
        make_section("s0", "Abstract", "Abstract."),
        make_section("s1", "Introduction", "Intro."),
        make_section("s2", "Method", "As shown in 公式(1), the loss is computed. 详见第3节。"),
        make_section("s3", "Experiments", "Experiment results."),
    ])
    chunks = CHUNKER.chunk(doc, "latex")
    method_chunks = [c for c in chunks if "Method" in c.section_title]
    # at least one method chunk should carry recorded cross-references
    assert any(c.references for c in method_chunks)


def test_chunk_ids_unique():
    doc = _structured_doc()
    chunks = CHUNKER.chunk(doc, "latex")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
