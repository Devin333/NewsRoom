from __future__ import annotations

from business.research.rag.evaluation.paper_answer_eval import EvidenceAnswerEvaluator, EvidenceAnswerSample
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair


def test_answer_evaluator_scores_fact_and_citation_grounding() -> None:
    pair = EvidenceQAPair(
        question="What do the experimental results show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl-1", "para-result"],
        required_evidence_types=["table", "paragraph"],
        gold_source_locators=["paper://p1/pdf#page=6", "paper://p1/pdf#page=7"],
        answer_facts=[
            "Table 1 reports accuracy and F1 scores.",
            "The model improves accuracy over the baseline.",
        ],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer=(
            "Table 1 reports accuracy and F1 scores, and the model improves "
            "accuracy over the baseline. [tbl-1] [para-result]"
        ),
        cited_chunk_ids=["tbl-1", "para-result"],
        cited_source_locators=["paper://p1/pdf#page=6&pdf_rect=1,2,3,4", "paper://p1/pdf#page=7"],
        context_chunk_ids=["tbl-1", "para-result"],
        metadata={"retrieved_chunk_ids": ["tbl-1", "para-result"]},
    )

    result = EvidenceAnswerEvaluator().evaluate([sample])
    score = result.scores[0]

    assert score.fact_coverage == 1.0
    assert score.retrieval_context_coverage == 1.0
    assert score.citation_grounding == 1.0
    assert score.citation_gold_coverage == 1.0
    assert score.source_locator_grounding == 1.0
    assert score.answer_success is True
    assert score.failure_reason == ""
    assert result.retrieval_context_coverage_score() == 1.0
    assert result.by_qa_type["table_qa"].success_rate() == 1.0


def test_answer_evaluator_marks_missing_facts_and_weak_citations() -> None:
    pair = EvidenceQAPair(
        question="What does the formula mean?",
        paper_id="p1",
        qa_type="formula_qa",
        gold_chunk_ids=["eq-1", "para-explain"],
        answer_facts=[
            "The equation computes attention weights.",
            "The paragraph explains queries keys and values.",
        ],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer="The equation computes attention weights. [eq-1]",
        cited_chunk_ids=["eq-1"],
        context_chunk_ids=["eq-1"],
        metadata={"retrieved_chunk_ids": ["eq-1", "para-explain"]},
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage == 0.5
    assert score.retrieval_context_coverage == 0.5
    assert score.citation_grounding == 0.5
    assert score.failure_reason == "missing_gold_in_llm_context"
    assert score.answer_success is False
    assert score.matched_facts == ("The equation computes attention weights.",)
    assert score.missing_facts == ("The paragraph explains queries keys and values.",)


def test_answer_evaluator_scores_negative_abstention() -> None:
    pair = EvidenceQAPair.negative(
        question="Does the paper discuss an unrelated future model?",
        paper_id="p1",
    )
    good = EvidenceAnswerSample(
        pair=pair,
        answer="The provided context does not mention any unrelated future model.",
    )
    good_plural = EvidenceAnswerSample(
        pair=pair,
        answer="The provided passages do not mention any unrelated future model.",
    )
    bad = EvidenceAnswerSample(
        pair=pair,
        answer="Yes, it uses the unrelated future model.",
    )

    result = EvidenceAnswerEvaluator().evaluate([good, good_plural, bad])

    assert [score.abstention_correct for score in result.scores] == [1.0, 1.0, 0.0]
    assert result.abstention_accuracy() == 2 / 3
    assert result.success_rate() == 2 / 3


def test_answer_evaluator_allows_no_fact_gold_but_requires_citation_when_present() -> None:
    pair = EvidenceQAPair(
        question="Where is the claim supported?",
        paper_id="p1",
        qa_type="citation_qa",
        gold_chunk_ids=["para-1"],
        gold_source_locators=["paper://p1/pdf#page=3"],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer="The claim is supported in the cited paragraph.",
        cited_chunk_ids=[],
        cited_source_locators=[],
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage is None
    assert score.citation_grounding == 0.0
    assert score.source_locator_grounding == 0.0
    assert score.answer_success is False


def test_answer_evaluator_treats_citation_qa_as_evidence_selection() -> None:
    pair = EvidenceQAPair(
        question="Which evidence supports the claim: Scaling language models helps NLP?",
        paper_id="p1",
        qa_type="citation_qa",
        gold_chunk_ids=["para-1"],
        gold_source_locators=["paper://p1/latex"],
        answer_facts=[
            "The NLP landscape has recently been revolutionized by language models [][inter alia]peters-etal-2018-deep.",
        ],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer="The support is the cited introduction paragraph about language models changing NLP. [1]",
        cited_chunk_ids=["para-1"],
        cited_source_locators=["paper://p1/latex"],
        context_chunk_ids=["para-1"],
        metadata={"retrieved_chunk_ids": ["para-1"]},
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage == 0.0
    assert score.citation_gold_coverage == 1.0
    assert score.answer_success is True
    assert score.failure_reason == ""


def test_answer_evaluator_soft_matches_latex_symbol_paraphrases() -> None:
    pair = EvidenceQAPair(
        question="How is Equation dd7633a3523b explained in the surrounding text?",
        paper_id="p1",
        qa_type="formula_explanation_qa",
        gold_chunk_ids=["eq-1", "para-1"],
        answer_facts=[
            (
                r"A typical choice of fn:qkv is \begin{equation} "
                r"f_{t:t\in\{q,k,v\}}(\x_i,i):=\W_{t:t\in\{q,k,v\}}(\x_i+\p_i), "
                r"\label{fn:adtv-posi} \end{equation} where $\p_i\in\mathbb{R}^{d}$ is a"
            )
        ],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer=(
            "The equation is a typical query/key/value mapping. It maps token x_i plus "
            "the positional vector p_i through W_t, and p_i is a d-dimensional vector "
            "determined by the token position. [1] [2]"
        ),
        cited_chunk_ids=["eq-1", "para-1"],
        context_chunk_ids=["eq-1", "para-1"],
        metadata={"retrieved_chunk_ids": ["eq-1", "para-1"]},
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage == 1.0
    assert score.answer_success is True


def test_answer_evaluator_reports_missing_gold_in_retrieval() -> None:
    pair = EvidenceQAPair(
        question="What does the formula mean?",
        paper_id="p1",
        qa_type="formula_qa",
        gold_chunk_ids=["eq-1"],
        answer_facts=["The formula computes a convolution kernel."],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer="The context discusses attention instead. [other]",
        cited_chunk_ids=["other"],
        context_chunk_ids=["other"],
        metadata={"retrieved_chunk_ids": ["other"]},
    )

    result = EvidenceAnswerEvaluator().evaluate([sample])
    score = result.scores[0]

    assert score.retrieval_context_coverage == 0.0
    assert score.failure_reason == "missing_gold_in_retrieval"
    assert result.failure_reason_counts() == {"missing_gold_in_retrieval": 1}


def test_answer_evaluator_soft_matches_long_structured_facts() -> None:
    pair = EvidenceQAPair(
        question="What does the figure show?",
        paper_id="p1",
        qa_type="figure_qa",
        gold_chunk_ids=["fig-1"],
        answer_facts=[
            "[Figure fig_1] Caption: Schematic of the objective we use in our baseline model. "
            "Nearby Context: In this example, we process a long sentence with multiple labels."
        ],
    )
    sample = EvidenceAnswerSample(
        pair=pair,
        answer="The figure shows a schematic of the baseline objective. [fig-1]",
        cited_chunk_ids=["fig-1"],
        context_chunk_ids=["fig-1"],
        metadata={"retrieved_chunk_ids": ["fig-1"]},
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage == 1.0
    assert score.answer_success is True
