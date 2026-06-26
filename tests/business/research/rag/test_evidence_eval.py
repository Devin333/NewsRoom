from __future__ import annotations

import pytest

from business.research.document.citation_spans import build_paragraph_span_metadata
from business.research.document.models import PaperChunk
from business.research.rag.evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    EvidenceRetrievalEvaluator,
    build_evidence_pairs_from_chunks,
    load_evidence_golden_set,
    save_evidence_golden_set,
)
from business.research.rag.retriever import RetrievalResult


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "paragraph",
    content: str = "The paper reports a useful result.",
    section_title: str = "Results",
    metadata: dict | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="nougat",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title=section_title,
        section_role=["experiment"],  # type: ignore[list-item]
        section_index=4,
        has_formula=chunk_type == "formula",
        has_figure=chunk_type == "figure",
        has_table=chunk_type == "table",
        content=content,
        metadata={
            "source_ref": f"arxiv://p1/{chunk_id}",
            **(metadata or {}),
        },
    )


class _FakeRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    def retrieve(self, request) -> RetrievalResult:
        self.calls.append((request.paper_id, request.question, request.limit))
        return self.result


def test_evidence_qa_pair_round_trips_source_chunk_metadata(tmp_path) -> None:
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        metadata={"source_locator": "paper://p1/pdf#page=6&pdf_rect=1,2,3,4"},
    )
    pair = EvidenceQAPair.from_source_chunk(
        question="What does Table 1 show?",
        chunk=table,
        answer_facts=["Table 1 reports the main result."],
    )

    assert pair.qa_type == "table_qa"
    assert pair.gold_chunk_ids == ["tbl-1"]
    assert pair.required_evidence_types == ["table"]
    assert pair.gold_source_locators == ["paper://p1/pdf#page=6&pdf_rect=1,2,3,4"]

    path = tmp_path / "golden.json"
    save_evidence_golden_set([pair], path)

    loaded = load_evidence_golden_set(path)
    assert loaded == [pair]


def test_negative_qa_can_have_no_gold_chunks() -> None:
    pair = EvidenceQAPair.negative(
        question="Does this paper discuss GPT-5 training data?",
        paper_id="p1",
    )

    assert pair.expected_behavior == "abstain"
    assert pair.gold_chunk_ids == []
    assert pair.qa_type == "negative_qa"


def test_answerable_evidence_qa_requires_gold_chunk() -> None:
    with pytest.raises(ValueError, match="requires at least one gold chunk id"):
        EvidenceQAPair(
            question="What is the method?",
            paper_id="p1",
            qa_type="paragraph_qa",
            expected_behavior="answer",
        )


def test_retrieval_evaluator_scores_multi_evidence_coverage_and_types() -> None:
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        content="[Table 1]\nAccuracy and F1 scores.",
        metadata={"source_locator": "paper://p1/pdf#page=6&pdf_rect=1,2,3,4"},
    )
    result_para = _chunk(
        "para-conclusion",
        chunk_type="paragraph",
        content="The results show the model improves accuracy.",
        metadata={"source_locator": "paper://p1/pdf#page=7"},
    )
    noise_parent = _chunk("sec-noise", content="Background noise.")
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[table],
        ref_chunks=[result_para],
        parent_chunks=[noise_parent],
        intent="table_query",
    ))
    pair = EvidenceQAPair(
        question="What do the experimental results show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-results", "para-conclusion"],
        required_evidence_types=["table", "paragraph"],
        gold_source_locators=[
            "paper://p1/pdf#page=6",
            "paper://p1/pdf#page=7",
        ],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1, 2, 3))

    assert result.total == 1
    assert result.answerable_total == 1
    assert result.hit_rate(1) == 1.0
    assert result.evidence_coverage(1) == 0.5
    assert result.evidence_coverage(2) == 1.0
    assert result.required_type_coverage(1) == 0.5
    assert result.required_type_coverage(2) == 1.0
    assert result.source_locator_coverage(1) == 0.5
    assert result.source_locator_coverage(2) == 1.0
    assert result.ndcg(2) == 1.0
    assert result.over_retrieval_rate(3) == 1.0
    assert result.by_qa_type["table_qa"].evidence_coverage(2) == 1.0


def test_retrieval_evaluator_counts_source_chunk_mapping_as_gold_hit() -> None:
    fixed_window = _chunk(
        "fixed-window-1",
        content="A fixed token window containing the table and its conclusion.",
        metadata={
            "source_chunk_ids": ["tbl-results", "para-conclusion"],
            "source_evidence_types": ["table", "paragraph"],
            "source_locators": [
                "paper://p1/pdf#page=6&pdf_rect=1,2,3,4",
                "paper://p1/pdf#page=7",
            ],
            "source_image_refs": ["tables/table1.png"],
        },
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[fixed_window],
        ref_chunks=[],
        parent_chunks=[],
        intent="table_query",
    ))
    pair = EvidenceQAPair(
        question="What do the experimental results show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-results", "para-conclusion"],
        required_evidence_types=["table", "paragraph"],
        gold_source_locators=[
            "paper://p1/pdf#page=6",
            "paper://p1/pdf#page=7",
        ],
        gold_image_refs=["tables/table1.png"],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))

    assert result.hit_rate(1) == 1.0
    assert result.evidence_coverage(1) == 1.0
    assert result.required_type_coverage(1) == 1.0
    assert result.source_locator_coverage(1) == 1.0
    assert result.image_recall(1) == 1.0
    assert result.visual_evidence_coverage(1) == 1.0
    assert result.over_retrieval_rate(1) == 0.0


def test_retrieval_evaluator_scores_main_citation_accuracy() -> None:
    content = "The main claim is grounded here."
    paragraph = _chunk(
        "para-main",
        content=content,
        metadata={
            "source_locator": "paper://p1/pdf#page=2",
            **build_paragraph_span_metadata(content=content),
        },
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[paragraph],
        ref_chunks=[],
        parent_chunks=[],
        intent="concept_method",
    ))
    pair = EvidenceQAPair(
        question="Where is the main claim grounded?",
        paper_id="p1",
        qa_type="citation_qa",
        gold_chunk_ids=["para-main"],
        gold_source_locators=["paper://p1/pdf#page=2"],
        gold_citation_spans=[{
            "chunk_id": "para-main",
            "snippet": "main claim",
            "span_kind": "main",
            "resolved_chunk_id": "para-main",
            "resolved_source_locator": "paper://p1/pdf#page=2",
        }],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))

    assert result.citation_accuracy(1) == 1.0
    assert result.overlap_citation_accuracy(1) == 0.0


def test_retrieval_evaluator_scores_overlap_citation_origin() -> None:
    content = "Borrowed sentence.\nCurrent paragraph body."
    current = _chunk(
        "para-current",
        content=content,
        metadata={
            "source_locator": "paper://p1/pdf#page=4",
            **build_paragraph_span_metadata(
                content=content,
                overlap_text="Borrowed sentence.",
                overlap_origin_chunk_id="para-previous",
                overlap_origin_source_locator="paper://p1/pdf#page=3",
            ),
        },
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[current],
        ref_chunks=[],
        parent_chunks=[],
        intent="concept_method",
    ))
    pair = EvidenceQAPair(
        question="Where should the borrowed sentence cite?",
        paper_id="p1",
        qa_type="citation_qa",
        gold_chunk_ids=["para-current"],
        gold_citation_spans=[{
            "chunk_id": "para-current",
            "snippet": "Borrowed sentence.",
            "span_kind": "overlap",
            "resolved_chunk_id": "para-previous",
            "resolved_source_locator": "paper://p1/pdf#page=3",
        }],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))

    assert result.citation_accuracy(1) == 1.0
    assert result.overlap_citation_accuracy(1) == 1.0


def test_negative_qa_is_excluded_from_retrieval_hit_denominator() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        content="[Equation]\nLaTeX:\na=b",
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[formula],
        ref_chunks=[],
        parent_chunks=[],
        intent="formula_query",
    ))
    answerable = EvidenceQAPair(
        question="What does the equation define?",
        paper_id="p1",
        qa_type="formula_qa",
        gold_chunk_ids=["eq-1"],
        required_evidence_types=["formula"],
    )
    negative = EvidenceQAPair.negative(
        question="Does the paper discuss an unrelated future model?",
        paper_id="p1",
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([answerable, negative], ks=(1,))

    assert result.total == 2
    assert result.answerable_total == 1
    assert result.abstain_total == 1
    assert result.hit_rate(1) == 1.0
    assert len(retriever.calls) == 1
    assert result.by_qa_type["negative_qa"].answerable_total == 0


def test_build_evidence_pairs_from_chunks_uses_typed_metadata() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        metadata={
            "source_locator": "paper://p1/pdf#page=3",
            "image_ref": "figures/fig1.png",
        },
    )

    pairs = build_evidence_pairs_from_chunks(
        [figure],
        questions_by_chunk_id={"fig-1": ["What does Figure 1 show?"]},
        domain="vision",
    )

    assert len(pairs) == 1
    assert pairs[0].qa_type == "figure_qa"
    assert pairs[0].required_evidence_types == ["figure"]
    assert pairs[0].gold_source_locators == ["paper://p1/pdf#page=3"]
    assert pairs[0].gold_image_refs == ["figures/fig1.png"]
    assert pairs[0].domain == "vision"


def test_retrieval_evaluator_scores_image_recall_for_visual_chunks() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        metadata={"image_ref": "figures/fig1.png"},
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[figure],
        ref_chunks=[],
        parent_chunks=[],
        intent="figure_query",
    ))
    pair = EvidenceQAPair(
        question="What does Figure 1 show?",
        paper_id="p1",
        qa_type="figure_qa",
        gold_chunk_ids=["fig-1"],
        required_evidence_types=["figure"],
        gold_image_refs=["figures/fig1.png"],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))

    assert result.image_recall(1) == 1.0
    assert result.visual_evidence_coverage(1) == 1.0


def test_evidence_golden_set_builder_creates_typed_pairs_from_chunks() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        content="[Equation]\nLaTeX:\na=b",
        metadata={
            "referenced_by_chunks": [{"chunk_id": "para-formula"}],
        },
    ).model_copy(update={
        "has_formula": True,
        "formula_latex": "a=b",
        "formula_description": "The equation defines a relation between a and b.",
    })
    formula_para = _chunk(
        "para-formula",
        content="The equation is explained as a relation between variables.",
        metadata={"source_ref": ""},
    )
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        content="[Table 1]\nCaption:\nMain results.",
        metadata={
            "table_id": "table-1",
            "nearby_context_chunk_id": "para-result",
            "image_ref": "tables/table1.png",
        },
    )
    result_para = _chunk("para-result", content="The results show improved accuracy.")
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        content="[Figure 1]\nCaption:\nArchitecture overview.",
        metadata={"figure_id": "fig-1", "image_ref": "figures/fig1.png"},
    )
    citation = _chunk(
        "para-cite",
        content="The method uses attention for sequence modeling.",
        metadata={"source_locator": "paper://p1/pdf#page=2"},
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2).build(
        [formula, formula_para, table, result_para, figure, citation],
        domain="nlp",
    )

    by_type = {pair.qa_type: pair for pair in pairs}
    assert by_type["formula_qa"].answer_facts == ["The equation defines a relation between a and b."]
    assert any(
        token in by_type["formula_qa"].question.lower()
        for token in ("equation", "formula")
    )
    assert by_type["formula_explanation_qa"].gold_chunk_ids == ["eq-1", "para-formula"]
    assert by_type["formula_explanation_qa"].required_evidence_types == ["formula", "paragraph"]
    assert any(
        token in by_type["formula_explanation_qa"].question.lower()
        for token in ("equation", "formula")
    )
    assert by_type["table_qa"].gold_chunk_ids == ["tbl-1", "para-result"]
    assert by_type["table_qa"].required_evidence_types == ["table", "paragraph"]
    assert "table" in by_type["table_qa"].question.lower()
    assert by_type["experiment_result_qa"].gold_chunk_ids == ["tbl-1", "para-result"]
    assert by_type["experiment_result_qa"].required_evidence_types == ["table", "paragraph"]
    assert "experiment results" in by_type["experiment_result_qa"].question.lower()
    assert "table" in by_type["experiment_result_qa"].question.lower()
    assert by_type["table_qa"].gold_image_refs == ["tables/table1.png"]
    assert by_type["figure_qa"].gold_image_refs == ["figures/fig1.png"]
    assert "figure" in by_type["figure_qa"].question.lower()
    assert any(
        pair.qa_type == "citation_qa"
        and pair.gold_source_locators == ["paper://p1/pdf#page=2"]
        for pair in pairs
    )
    assert by_type["negative_qa"].expected_behavior == "abstain"
    assert all(pair.domain == "nlp" for pair in pairs)


def test_golden_set_builder_uses_standalone_visual_and_formula_chunks_for_special_qa() -> None:
    paragraph_with_figure = _chunk(
        "para-mentions-figure",
        content="Figure 1 shows the architecture.",
    ).model_copy(update={"has_figure": True, "figure_id": "fig-1"})
    standalone_figure = _chunk(
        "fig-1",
        chunk_type="figure",
        content="[Figure 1]\nCaption:\nArchitecture.",
        metadata={"figure_id": "fig-1"},
    )
    paragraph_with_formula = _chunk(
        "para-mentions-formula",
        content="The objective uses $L=x$.",
    ).model_copy(update={"has_formula": True, "formula_latex": "$L=x$"})
    standalone_formula = _chunk(
        "eq-1",
        chunk_type="formula",
        content="[Equation]\nLaTeX:\n$L=x$",
    ).model_copy(update={"has_formula": True, "formula_latex": "$L=x$"})

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=5, include_negative=False).build([
        paragraph_with_figure,
        standalone_figure,
        paragraph_with_formula,
        standalone_formula,
    ])

    by_type = {pair.qa_type: pair for pair in pairs}
    assert by_type["figure_qa"].gold_chunk_ids == ["fig-1"]
    assert by_type["formula_qa"].gold_chunk_ids == ["eq-1"]
