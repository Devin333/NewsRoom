from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.field_text import extract_field_texts


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
    assert "attention arrows" in fields.caption
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
