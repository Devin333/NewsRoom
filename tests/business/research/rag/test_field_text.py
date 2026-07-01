from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.adapters.paper_field_text import extract_field_texts


def test_extract_field_texts_returns_available_fields_and_sources():
    chunk = PaperChunk(
        chunk_id="fig-1",
        paper_id="p1",
        parse_source="latex",
        chunk_type="figure",
        section_title="Model Architecture",
        section_role=["method"],
        section_index=2,
        has_formula=True,
        formula_latex=r"\operatorname{Attention}(Q,K,V)",
        formula_description="Attention maps queries keys and values.",
        content=(
            "[Figure fig1]\n"
            "Caption:\n"
            "Transformer architecture overview.\n\n"
            "Body text mentions encoder decoder attention."
        ),
        metadata={
            "caption_text": "Transformer architecture overview.",
            "visual_description": "The image shows stacked encoder and decoder blocks with attention arrows.",
            "content_sources": ["caption", "nearby_context"],
        },
    )

    fields = extract_field_texts(chunk)

    assert fields.title == "Model Architecture"
    assert "caption" in fields.available_fields()
    assert "equation" in fields.available_fields()
    assert fields.sources_for("title") == ("section_title",)
    assert "metadata.caption_text" in fields.sources_for("caption")
    assert "metadata.visual_description" in fields.sources_for("caption")
    assert "metadata.visual_description" in fields.sources_for("visual_description")
    assert "attention arrows" in fields.caption
    assert "attention arrows" in fields.visual_description
    assert "formula_latex" in fields.sources_for("equation")
    assert fields.text_for("missing") == ""


def test_extract_field_texts_omits_missing_abstract_field():
    chunk = PaperChunk(
        chunk_id="para-1",
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=2,
        content="Method body.",
    )

    fields = extract_field_texts(chunk)

    assert "abstract" not in fields.available_fields()
    assert fields.abstract == ""
    assert fields.body == "Method body."


def test_extract_field_texts_includes_formula_structure_metadata():
    chunk = PaperChunk(
        chunk_id="eq-1",
        paper_id="p1",
        parse_source="latex",
        chunk_type="formula",
        section_title="Method",
        section_role=["method"],
        section_index=2,
        has_formula=True,
        formula_latex=r"\operatorname{Attention}(Q,K,V)",
        content="Formula content.",
        metadata={
            "formula_normalized_latex": r"\operatorname{attention}(q,k,v)",
            "formula_symbols": ["Q", "K", "V"],
            "formula_operators": ["operatorname", "Attention"],
            "formula_referenced_text": ["The paragraph explains query key value attention."],
        },
    )

    fields = extract_field_texts(chunk)

    assert "metadata.formula_normalized_latex" in fields.sources_for("equation")
    assert "metadata.formula_symbols" in fields.sources_for("equation")
    assert "metadata.formula_operators" in fields.sources_for("equation")
    assert "metadata.formula_referenced_text" in fields.sources_for("equation")
    assert "metadata.formula_referenced_text" in fields.sources_for("referenced_text")
    assert "query key value attention" in fields.equation
    assert "query key value attention" in fields.referenced_text


def test_extract_field_texts_derives_formula_structure_when_metadata_missing():
    chunk = PaperChunk(
        chunk_id="eq-2",
        paper_id="p1",
        parse_source="latex",
        chunk_type="formula",
        section_title="Method",
        section_role=["method"],
        section_index=2,
        has_formula=True,
        formula_latex=r"\operatorname{Attention}(Q,K,V)=\operatorname{softmax}(QK^T)",
        formula_description="Attention maps query key value vectors.",
        content="Equation 2 defines the attention calculation.",
        metadata={"reference_labels": ["2"]},
    )

    fields = extract_field_texts(chunk)

    assert "metadata.formula_normalized_latex" in fields.sources_for("equation")
    assert "metadata.formula_symbols" in fields.sources_for("equation")
    assert "metadata.formula_operators" in fields.sources_for("equation")
    assert "metadata.formula_structure_tokens" in fields.sources_for("equation")
    assert "metadata.formula_reference_labels" in fields.sources_for("equation")
    assert "metadata.formula_context_terms" in fields.sources_for("equation")
    assert "attention" in fields.equation.casefold()
    assert "Q" in fields.equation
    assert "function_call" in fields.equation


def test_extract_field_texts_includes_table_structure_metadata():
    chunk = PaperChunk(
        chunk_id="tbl-1",
        paper_id="p1",
        parse_source="latex",
        chunk_type="table",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=3,
        has_table=True,
        content="[Table 1]\nCaption:\nMain benchmark results.",
        metadata={
            "table_id": "tbl-1",
            "semantic_text": "Table 1 reports BLEU and accuracy for the proposed model.",
            "table_text": "Model | BLEU | Accuracy",
            "columns": ["Model", "BLEU", "Accuracy"],
            "rows": [
                {"model": "baseline", "bleu": "26.1", "accuracy": "72.0"},
                {"model": "ours", "bleu": "29.4", "accuracy": "76.5"},
            ],
        },
    )

    fields = extract_field_texts(chunk)

    assert "metadata.semantic_text" in fields.sources_for("body")
    assert "metadata.table_text" in fields.sources_for("body")
    assert "metadata.table_columns" in fields.sources_for("body")
    assert "metadata.table_rows" in fields.sources_for("body")
    assert "metadata.columns" in fields.sources_for("table_columns")
    assert "metadata.rows" in fields.sources_for("table_rows")
    assert "proposed model" in fields.body
    assert "baseline | 26.1 | 72.0" in fields.body
    assert "Model" in fields.table_columns
    assert "baseline | 26.1 | 72.0" in fields.table_rows
