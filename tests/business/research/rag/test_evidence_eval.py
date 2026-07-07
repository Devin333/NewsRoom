from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from business.research.document.citation_spans import build_paragraph_span_metadata
from business.research.document.models import PaperChunk
from business.research.rag.evaluation.paper_evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    EvidenceRetrievalEvaluator,
    build_evidence_pairs_from_chunks,
    formula_failure_diagnostics,
    hydrate_evidence_pairs_from_chunks,
    load_evidence_golden_set,
    save_evidence_golden_set,
)
from business.research.rag.evaluation.paper_evaluation_report import EvidenceRegressionReport
from business.research.rag.retrieval.paper_claim_index import extract_claim_records
from business.research.rag.retrieval.paper_retriever import RetrievalResult


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


def test_repository_golden_set_has_answer_and_abstain_behavior_samples() -> None:
    pairs = load_evidence_golden_set(Path("data/eval/golden_set.json"))
    behavior_counts = Counter(pair.expected_behavior for pair in pairs)

    assert len(pairs) == 79
    assert behavior_counts["answer"] == 67
    assert behavior_counts["abstain"] >= 10
    assert all(pair.expected_behavior in {"answer", "abstain"} for pair in pairs)
    answer_pairs = [pair for pair in pairs if pair.expected_behavior == "answer"]
    abstain_pairs = [pair for pair in pairs if pair.expected_behavior == "abstain"]
    assert all(pair.qa_type == "legacy_qa" for pair in answer_pairs)
    assert all(pair.gold_chunk_ids for pair in answer_pairs)
    assert all(pair.qa_type == "negative_qa" for pair in abstain_pairs)
    assert all(not pair.gold_chunk_ids for pair in abstain_pairs)
    assert pairs[0].metadata["source_chunk_id"] == pairs[0].gold_chunk_ids[0]


def test_hydrate_evidence_pairs_from_chunks_attaches_current_corpus_metadata() -> None:
    chunk = _chunk(
        "legacy-para",
        metadata={"source_locator": "paper://p1/pdf#page=3"},
    )
    pair = EvidenceQAPair(
        question="What result is reported?",
        paper_id="p1",
        qa_type="legacy_qa",
        gold_chunk_ids=["legacy-para"],
    )

    hydrated, summary = hydrate_evidence_pairs_from_chunks([pair], [chunk])

    assert summary["hydrated_pairs"] == 1
    assert summary["locator_attached_pairs"] == 1
    assert summary["type_attached_pairs"] == 1
    assert summary["missing_gold_chunk_pairs"] == 0
    assert hydrated[0].gold_source_locators == ["paper://p1/pdf#page=3"]
    assert hydrated[0].required_evidence_types == ["paragraph"]
    assert hydrated[0].supporting_evidence_group["primary_evidence_ids"] == ["legacy-para"]
    assert hydrated[0].metadata["hydrated_from_current_corpus"] is True


def test_hydrate_evidence_pairs_from_chunks_reports_missing_gold_ids() -> None:
    pair = EvidenceQAPair(
        question="What result is reported?",
        paper_id="p1",
        qa_type="legacy_qa",
        gold_chunk_ids=["missing-para"],
    )

    hydrated, summary = hydrate_evidence_pairs_from_chunks([pair], [])

    assert summary["hydrated_pairs"] == 0
    assert summary["missing_gold_chunk_pairs"] == 1
    assert summary["missing_gold_chunk_ids"] == ["missing-para"]
    assert hydrated[0].metadata["missing_gold_chunk_ids"] == ["missing-para"]


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


def test_golden_set_builder_attaches_supporting_evidence_group() -> None:
    parent = _chunk(
        "para-formula",
        content="The Hamiltonian ODE defines the system dynamics and explains the variables.",
    )
    formula = _chunk(
        "eq-hamiltonian",
        chunk_type="formula",
        content="Equation: \\dot{y}=J^{-1}\\nabla H(y)",
        metadata={"source_locator": "paper://p1/pdf#page=3&rect=1,2,3,4"},
    )
    formula.parent_chunk_id = parent.chunk_id
    formula.formula_latex = "\\dot{y}=J^{-1}\\nabla H(y)"

    pairs = EvidenceGoldenSetBuilder(include_negative=False).build([parent, formula])
    formula_pair = next(pair for pair in pairs if pair.qa_type == "formula_qa")

    assert formula_pair.supporting_evidence_group_id.startswith("eg_")
    assert formula_pair.equivalent_gold_chunk_ids == ["eq-hamiltonian", "para-formula"]
    assert formula_pair.required_primary_evidence_ids == ["eq-hamiltonian"]
    assert formula_pair.acceptable_support_evidence_ids == ["para-formula"]
    assert formula_pair.supporting_evidence_group["primary_evidence_ids"] == ["eq-hamiltonian"]
    assert formula_pair.supporting_evidence_group["interpretation_context_ids"] == ["para-formula"]


def test_retrieval_evaluator_reports_strict_and_equivalent_hits() -> None:
    parent = _chunk("para-formula", content="The Hamiltonian ODE defines the system dynamics.")
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[parent],
        ref_chunks=[],
        parent_chunks=[],
        intent="formula_query",
    ))
    pair = EvidenceQAPair(
        question="How is the Hamiltonian ODE defined?",
        paper_id="p1",
        qa_type="formula_qa",
        gold_chunk_ids=["eq-hamiltonian"],
        equivalent_gold_chunk_ids=["eq-hamiltonian", "para-formula"],
        required_evidence_types=["formula"],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))
    report = EvidenceRegressionReport(retrieval=result).to_dict()

    assert result.hit_rate(1) == 0.0
    assert result.equivalent_hit_rate(1) == 1.0
    assert report["retrieval"]["by_k"]["1"]["strict_hit_rate"] == 0.0
    assert report["retrieval"]["by_k"]["1"]["equivalent_hit_rate"] == 1.0
    assert report["retrieval"]["strict_mrr"] == 0.0
    assert report["retrieval"]["equivalent_mrr"] == 1.0


def test_retrieval_evaluator_reports_intent_and_route_distribution() -> None:
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        content="[Table 1]\nBLEU and accuracy scores.",
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[table],
        ref_chunks=[],
        parent_chunks=[],
        intent="numerical_result",
        metadata={
            "intent": "numerical_result",
            "recall_routes": ["table_chunks", "result_paragraphs", "conclusion_context"],
        },
    ))
    pair = EvidenceQAPair(
        question="What quantitative evidence do the reported experiments provide?",
        paper_id="p1",
        qa_type="experiment_result_qa",
        gold_chunk_ids=["tbl-results"],
        required_evidence_types=["table"],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1,))
    report = EvidenceRegressionReport(retrieval=result).to_dict()

    assert result.intent_distribution == {"numerical_result": 1}
    assert result.route_distribution == {
        "conclusion_context": 1,
        "result_paragraphs": 1,
        "table_chunks": 1,
    }
    assert result.intent_confusion == {"experiment_result_qa": {"numerical_result": 1}}
    assert report["retrieval"]["route_distribution"]["table_chunks"] == 1
    assert report["retrieval"]["intent_confusion"]["experiment_result_qa"]["numerical_result"] == 1


def test_formula_failure_diagnostics_explain_formula_context_miss() -> None:
    wrong_formula = _chunk(
        "eq-wrong",
        chunk_type="formula",
        content="Equation: E = mc^2",
        metadata={
            "formula_sparse_score": 0.8,
            "formula_symbol_score": 0.8,
            "child_final_score": 0.9,
        },
    )
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[wrong_formula],
        ref_chunks=[],
        parent_chunks=[],
        intent="formula_query",
        metadata={
            "retrieval_policy": "paper_formula_rag_v1",
            "intent": "formula_query",
            "formula_sparse_enabled": True,
            "formula_sparse_recalled": 1,
            "formula_context_returned": 0,
        },
    ))
    pair = EvidenceQAPair(
        question="How is Equation 2 explained in the surrounding text?",
        paper_id="p1",
        qa_type="formula_explanation_qa",
        gold_chunk_ids=["eq-attn", "para-attn"],
        equivalent_gold_chunk_ids=["eq-attn", "para-attn"],
        required_evidence_types=["formula", "paragraph"],
    )

    result = EvidenceRetrievalEvaluator(retriever).evaluate([pair], ks=(1, 10))
    diagnostics = formula_failure_diagnostics(result, top_k=10)

    assert diagnostics["total_failures"] == 1
    item = diagnostics["items"][0]
    assert "missing_gold_in_retrieval" in item["failure_reasons"]
    assert "formula_context_missing" in item["failure_reasons"]
    assert "graph_expansion_missing" in item["failure_reasons"]
    assert "equation_label_miss" in item["failure_reasons"]
    assert item["suggested_action"] == "fix_formula_label_metadata"
    assert item["score_breakdown"][0]["formula_sparse_score"] == 0.8
    assert diagnostics["reason_counts"]["graph_expansion_missing"] == 1


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


def test_golden_set_builder_uses_claim_index_ids_for_citation_gold() -> None:
    paragraph = _chunk(
        "para-claim",
        section_title="Introduction",
        content="We introduce a scalable retrieval method that improves scientific paper QA.",
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2, include_negative=False).build([paragraph])
    citation_pair = next(pair for pair in pairs if pair.qa_type == "citation_qa")
    claim_ids = [record.claim_id for record in extract_claim_records(paragraph)]

    assert citation_pair.gold_claim_ids
    assert set(citation_pair.gold_claim_ids).issubset(set(claim_ids))


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


def test_image_recall_ignores_pairs_without_gold_images() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        metadata={"image_ref": "figures/fig1.png"},
    )
    formula = _chunk("eq-1", chunk_type="formula")
    retriever = _FakeRetriever(RetrievalResult(
        child_chunks=[figure, formula],
        ref_chunks=[],
        parent_chunks=[],
        intent="figure_query",
    ))
    pairs = [
        EvidenceQAPair(
            question="What does the equation define?",
            paper_id="p1",
            qa_type="formula_qa",
            gold_chunk_ids=["eq-1"],
            required_evidence_types=["formula"],
        ),
        EvidenceQAPair(
            question="What does Figure 1 show?",
            paper_id="p1",
            qa_type="figure_qa",
            gold_chunk_ids=["fig-1"],
            required_evidence_types=["figure"],
            gold_image_refs=["figures/fig1.png"],
        ),
    ]

    result = EvidenceRetrievalEvaluator(retriever).evaluate(pairs, ks=(1,))

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
    assert by_type["experiment_result_qa"].gold_chunk_ids == ["tbl-1"]
    assert by_type["experiment_result_qa"].required_evidence_types == ["table"]
    assert "experiment results" in by_type["experiment_result_qa"].question.lower()
    assert "table" in by_type["experiment_result_qa"].question.lower()
    assert "main results" in by_type["experiment_result_qa"].question.lower()
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


def test_formula_explanation_pair_prefers_symbol_explanation_sentence() -> None:
    formula = _chunk(
        "eq-qkv",
        chunk_type="formula",
        content="[Equation eq_qkv]\nLaTeX:\nq_m=f_q(x_m,m), k_n=f_k(x_n,n), v_n=f_v(x_n,n)",
        metadata={
            "equation_id": "eq-qkv",
            "referenced_by_chunks": [{"chunk_id": "para-qkv"}],
        },
    ).model_copy(update={
        "has_formula": True,
        "formula_latex": r"\q_m=f_q(\x_m,m), \k_n=f_k(\x_n,n), \v_n=f_v(\x_n,n)",
    })
    context = _chunk(
        "para-qkv",
        content=(
            "Let S_N be a sequence of input tokens and E_N be their embeddings. "
            "The self-attention first incorporates position information into the word embeddings. "
            "where q_m, k_n and v_n incorporate the mth and nth positions through f_q, f_k and f_v."
        ),
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2).build([formula, context], domain="nlp")
    pair = next(item for item in pairs if item.qa_type == "formula_explanation_qa")

    assert any("q_m, k_n and v_n incorporate" in fact for fact in pair.answer_facts)
    assert not any(fact.startswith("Let S_N be a sequence") for fact in pair.answer_facts)


def test_formula_explanation_pair_uses_near_formula_context_window() -> None:
    formula = _chunk(
        "eq-erm",
        chunk_type="formula",
        content="[Equation eq:def:erm]\nLaTeX:\n\\begin{equation}\\label{eq:def:erm} L(W)=x \\end{equation}",
        metadata={
            "equation_id": "eq:def:erm",
            "referenced_by_chunks": [{"chunk_id": "para-setting"}],
        },
    ).model_copy(update={
        "has_formula": True,
        "formula_latex": "\\begin{equation}\\label{eq:def:erm} L(W)=x \\end{equation}",
    })
    context = _chunk(
        "para-setting",
        content=(
            "Model Setting. We consider the regularized empirical risk minimization problem "
            "\\begin{equation}\\label{eq:def:erm} L(W)=x \\end{equation} "
            "for the class of quadratic two-layer neural networks. "
            + "Additional derivation sentence. " * 80
            + "We therefore consider labels generated by a centered quadratic model with Gaussian noise."
        ),
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2).build([formula, context])
    pair = next(item for item in pairs if item.qa_type == "formula_explanation_qa")

    assert any("regularized empirical risk minimization" in fact for fact in pair.answer_facts)
    assert not any("labels generated by a centered quadratic model" in fact for fact in pair.answer_facts)


def test_citation_pair_strips_latex_section_label_prefix() -> None:
    chunk = _chunk(
        "para-cite-label",
        content="sec:intro When we read a story, we bring implicit knowledge about the physical world.",
        metadata={"source_locator": "paper://p1/pdf#page=1"},
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=1).build([chunk], domain="nlp")
    citation_pairs = [pair for pair in pairs if pair.qa_type == "citation_qa"]

    assert len(citation_pairs) == 1
    assert citation_pairs[0].question.startswith("Which evidence supports the claim: When we read a story")
    assert citation_pairs[0].answer_facts == [
        "When we read a story, we bring implicit knowledge about the physical world."
    ]


def test_visual_questions_include_caption_topic_to_reduce_label_ambiguity() -> None:
    table = _chunk(
        "tbl-ambiguous",
        chunk_type="table",
        content="[Table tbl_1]\nCaption:\nReward model results across helpfulness and safety benchmarks.",
        metadata={"reference_labels": ["3"], "image_ref": "tables/table3.png"},
    )
    figure = _chunk(
        "fig-ambiguous",
        chunk_type="figure",
        content="[Figure fig_1]\nCaption:\nArchitecture overview for the reward model.",
        metadata={"reference_labels": ["2"], "image_ref": "figures/fig2.png"},
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2).build([table, figure], domain="nlp")
    questions = {pair.qa_type: pair.question for pair in pairs}

    assert "Table 3, about Reward model results" in questions["table_qa"]
    assert "Figure 2, captioned Architecture overview" in questions["figure_qa"]


def test_figure_pair_uses_nearby_context_as_answer_fact() -> None:
    figure = _chunk(
        "fig-short",
        chunk_type="figure",
        content="[Figure 1]\nCaption:\nCorrelation between sequence probability and correctness.",
        metadata={
            "figure_id": "fig-short",
            "nearby_context_chunk_id": "para-figure",
            "image_ref": "figures/fig-short.png",
        },
    )
    context = _chunk(
        "para-figure",
        content=(
            "The paper analyzes the correlation between sequence probability and correctness, "
            "showing that probability weighting can underperform."
        ),
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2, include_negative=False).build([figure, context])
    pair = next(item for item in pairs if item.qa_type == "figure_qa")

    assert "para-figure" in pair.gold_chunk_ids
    assert any("sequence probability and correctness" in fact for fact in pair.answer_facts)


def test_figure_pair_skips_incomplete_caption_without_visual_description() -> None:
    figure = _chunk(
        "fig-incomplete",
        chunk_type="figure",
        content="[Figure 1]\nCaption:\nThe correlation between",
        metadata={"figure_id": "fig-incomplete", "image_ref": "figures/fig-incomplete.png"},
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2, include_negative=False).build([figure])

    assert "figure_qa" not in {pair.qa_type for pair in pairs}


def test_blind_detemplated_profile_rewrites_questions_without_direct_labels_or_caption_copy() -> None:
    table = _chunk(
        "tbl-blind",
        chunk_type="table",
        content="[Table 3]\nCaption:\nReward model results across helpfulness and safety benchmarks.",
        metadata={"reference_labels": ["3"], "image_ref": "tables/table3.png"},
    )
    figure = _chunk(
        "fig-blind",
        chunk_type="figure",
        content="[Figure 2]\nCaption:\nArchitecture overview for the reward model.",
        metadata={"reference_labels": ["2"], "image_ref": "figures/fig2.png"},
    )
    formula = _chunk(
        "eq-blind",
        chunk_type="formula",
        content="[Equation eq_abc]\nLaTeX:\ny = x + 1",
    ).model_copy(update={"has_formula": True, "formula_latex": "y = x + 1"})
    citation = _chunk(
        "para-blind",
        content="When we read a story, we bring implicit knowledge about the physical world.",
        metadata={"source_locator": "paper://p1/pdf#page=1"},
    )

    pairs = EvidenceGoldenSetBuilder(
        max_pairs_per_type=5,
        include_negative=False,
        question_profile="blind_detemplated",
    ).build([table, figure, formula, citation])
    by_type = {pair.qa_type: pair for pair in pairs}

    assert by_type["table_qa"].gold_chunk_ids == ["tbl-blind"]
    assert "Table 3" not in by_type["table_qa"].question
    assert "Reward model results across helpfulness" not in by_type["table_qa"].question
    assert "Figure 2" not in by_type["figure_qa"].question
    assert "Architecture overview for the reward model" not in by_type["figure_qa"].question
    assert "eq_abc" not in by_type["formula_qa"].question
    assert "When we read a story" not in by_type["citation_qa"].question
    assert by_type["table_qa"].metadata["question_profile"] == "blind_detemplated"
    assert by_type["table_qa"].metadata["blind_evaluation"] is True
    assert by_type["table_qa"].metadata["template_question"].startswith("What do the experimental results around Table 3")


def test_blind_semantic_profile_preserves_short_anchors_without_direct_labels() -> None:
    table = _chunk(
        "tbl-semantic",
        chunk_type="table",
        content="[Table 3]\nCaption:\nReward model results across helpfulness and safety benchmarks.",
        metadata={
            "reference_labels": ["3"],
            "image_ref": "tables/table3.png",
            "rows": [{"benchmark": "helpfulness", "score": "92"}, {"benchmark": "safety", "score": "88"}],
        },
    )
    figure = _chunk(
        "fig-semantic",
        chunk_type="figure",
        content="[Figure 2]\nCaption:\nArchitecture overview for the reward model.",
        metadata={"reference_labels": ["2"], "image_ref": "figures/fig2.png"},
    )
    formula = _chunk(
        "eq-semantic",
        chunk_type="formula",
        content="[Equation eq_ranking]\nLaTeX:\nL_ranking = -log(sigma(r_chosen - r_rejected))",
    ).model_copy(update={
        "has_formula": True,
        "formula_latex": "L_ranking = -log(sigma(r_chosen - r_rejected))",
        "formula_description": "ranking loss compares chosen and rejected reward responses",
    })

    pairs = EvidenceGoldenSetBuilder(
        max_pairs_per_type=5,
        include_negative=False,
        question_profile="blind_semantic",
    ).build([table, figure, formula])
    by_type = {pair.qa_type: pair for pair in pairs}

    assert "Table 3" not in by_type["table_qa"].question
    assert "Figure 2" not in by_type["figure_qa"].question
    assert "eq_ranking" not in by_type["formula_qa"].question
    assert "Reward model results across helpfulness and safety benchmarks" not in by_type["table_qa"].question
    assert "reward" in by_type["table_qa"].question.casefold()
    assert "helpfulness" in by_type["table_qa"].question.casefold()
    assert "architecture" in by_type["figure_qa"].question.casefold()
    assert "ranking" in by_type["formula_qa"].question.casefold()
    assert by_type["table_qa"].metadata["question_profile"] == "blind_semantic"
    assert by_type["table_qa"].metadata["detemplate_policy"] == "semantic_anchors_no_labels_v1"
    assert len(by_type["table_qa"].metadata["semantic_anchors"]) >= 3
    assert by_type["formula_qa"].metadata["semantic_anchors"][:2] == ["ranking", "loss"]


def test_table_pair_skips_label_only_nearby_context_gold() -> None:
    table = _chunk(
        "tbl-zero-shot",
        chunk_type="table",
        content="[Table tbl_1]\nCaption:\nZero-shot evaluations.\nRows: S6 | 99.8",
        metadata={
            "nearby_context_chunk_id": "sec-intro",
            "caption_text": "Table 1: Selective Copying accuracy.",
        },
    )
    label_only = _chunk("sec-intro", content="sec:intro")

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=2, include_negative=False).build(
        [table, label_only],
        domain="nlp",
    )
    table_pair = next(pair for pair in pairs if pair.qa_type == "table_qa")

    assert table_pair.gold_chunk_ids == ["tbl-zero-shot"]
    assert table_pair.required_evidence_types == ["table"]


def test_table_pair_ignores_conflicting_metadata_caption() -> None:
    table = _chunk(
        "tbl-conflict",
        chunk_type="table",
        content=(
            "[Table tbl_8]\n"
            "Caption:\n"
            "Ablations: Architecture and SSM layer.\n"
            "Rows: Mamba | S6 | perplexity 9.64"
        ),
        metadata={
            "caption_text": "Table 7: Ablations: Selective parameters. Delta is the most important parameter.",
            "table_id": "tbl-conflict",
        },
    )

    pairs = EvidenceGoldenSetBuilder(
        max_pairs_per_type=2,
        include_negative=False,
        question_profile="blind_semantic",
    ).build([table])
    table_pair = next(pair for pair in pairs if pair.qa_type == "table_qa")

    assert "Architecture" in table_pair.question
    assert "Selective" not in table_pair.question
    assert any("Architecture and SSM layer" in fact for fact in table_pair.answer_facts)
    assert not any("Selective parameters" in fact for fact in table_pair.answer_facts)


def test_experiment_result_pairs_require_result_like_table() -> None:
    architecture_table = _chunk(
        "tbl-architecture",
        chunk_type="table",
        content=(
            "[Table 1]\nCaption:\nModel architecture details.\n"
            "Nearby Context: The introduction mentions astonishing results."
        ),
        metadata={
            "table_id": "tbl-architecture",
            "nearby_context_chunk_id": "para-result",
        },
    )
    result_para = _chunk("para-result", content="The results show better accuracy.")

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=5, include_negative=False).build([
        architecture_table,
        result_para,
    ])

    assert "experiment_result_qa" not in {pair.qa_type for pair in pairs}


def test_experiment_result_pair_skips_fragmented_table_columns() -> None:
    fragmented_table = _chunk(
        "tbl-fragmented",
        chunk_type="table",
        content=(
            "[Table 4]\n"
            "Caption:\n"
            "Performance of all models in accuracy.\n"
            "Columns: R | e | a | s | o | n | x | p | l | a_2 | n_2 | ti | o_2 | column_22 | column_23\n"
            "Rows: 84 | 91"
        ),
    )

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=5, include_negative=False).build([fragmented_table])
    qa_types = {pair.qa_type for pair in pairs}

    assert "table_qa" in qa_types
    assert "experiment_result_qa" not in qa_types


def test_experiment_result_pair_keeps_explicit_result_reference_context() -> None:
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        content="[Table 1]\nCaption:\nBenchmark results on SuperGLUE.",
        metadata={
            "table_id": "tbl-results",
            "referenced_by_chunks": [{"chunk_id": "para-result", "text_ref": "Table 1"}],
        },
    )
    result_para = _chunk("para-result", content="Table 1 shows the model improves accuracy.")

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=5, include_negative=False).build([
        table,
        result_para,
    ])
    result_pair = next(pair for pair in pairs if pair.qa_type == "experiment_result_qa")

    assert result_pair.gold_chunk_ids == ["tbl-results", "para-result"]
    assert result_pair.required_evidence_types == ["table", "paragraph"]
    assert result_pair.metadata["context_source"] == "explicit_reference"


def test_golden_set_builder_samples_table_result_pairs_across_papers() -> None:
    chunks: list[PaperChunk] = []
    for paper_id in ("p1", "p2", "p3"):
        for index in range(3):
            table = _chunk(
                f"{paper_id}-tbl-{index}",
                chunk_type="table",
                content=f"[Table {index}]\nCaption:\nBenchmark results for {paper_id}.",
                metadata={
                    "table_id": f"{paper_id}-tbl-{index}",
                    "nearby_context_chunk_id": f"{paper_id}-para-result",
                },
            ).model_copy(update={"paper_id": paper_id})
            para = _chunk(
                f"{paper_id}-para-result",
                content=f"The experimental results show improved accuracy for {paper_id}.",
            ).model_copy(update={"paper_id": paper_id})
            chunks.extend([table, para])

    pairs = EvidenceGoldenSetBuilder(max_pairs_per_type=3, include_negative=False).build(chunks)
    result_pairs = [pair for pair in pairs if pair.qa_type == "experiment_result_qa"]

    assert len(result_pairs) == 3
    assert {pair.paper_id for pair in result_pairs} == {"p1", "p2", "p3"}


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
