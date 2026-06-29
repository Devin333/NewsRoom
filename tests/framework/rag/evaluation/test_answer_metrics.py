from __future__ import annotations

from framework.rag.evaluation import AnswerMetricCase, RAGFailureReason, evaluate_answer_case, score_answer_case


def test_answer_metrics_are_deterministic_and_grounded_in_context():
    case = AnswerMetricCase(
        case_id="case-1",
        question="What does the experiment show?",
        answer="The experiment shows higher accuracy and lower loss. [ev-1]",
        expected_facts=("higher accuracy", "lower loss"),
        cited_evidence_ids=("ev-1",),
        context_evidence_ids=("ev-1", "ev-2"),
    )

    metrics = {metric.name: metric.value for metric in evaluate_answer_case(case)}

    assert metrics["fact_coverage"] == 1.0
    assert metrics["citation_grounding"] == 1.0
    assert metrics["answer_relevance"] > 0
    assert metrics["faithfulness_proxy"] == 1.0
    assert metrics["abstention_accuracy"] == 1.0


def test_answer_metrics_detect_expected_abstention():
    case = AnswerMetricCase(
        case_id="case-2",
        question="What is missing?",
        answer="Insufficient evidence to answer.",
        expected_abstain=True,
    )

    metrics = {metric.name: metric.value for metric in evaluate_answer_case(case)}

    assert metrics["faithfulness_proxy"] == 1.0
    assert metrics["abstention_accuracy"] == 1.0


def test_score_answer_case_tracks_context_citation_locator_and_success():
    case = AnswerMetricCase(
        case_id="case-3",
        question="What do the results show?",
        answer="Table 1 reports accuracy and F1, and the model improves accuracy. [tbl-1] [para-1]",
        expected_facts=(
            "Table 1 reports accuracy and F1.",
            "The model improves accuracy.",
        ),
        cited_evidence_ids=("tbl-1", "para-1"),
        context_evidence_ids=("tbl-1", "para-1"),
        gold_evidence_ids=("tbl-1", "para-1"),
        cited_source_locators=("paper://p/pdf#page=6&rect=1,2,3,4", "paper://p/pdf#page=7"),
        gold_source_locators=("paper://p/pdf#page=6", "paper://p/pdf#page=7"),
        retrieved_evidence_ids=("tbl-1", "para-1"),
    )

    score = score_answer_case(case)

    assert score.fact_coverage == 1.0
    assert score.retrieval_context_coverage == 1.0
    assert score.citation_grounding == 1.0
    assert score.source_locator_grounding == 1.0
    assert score.answer_success is True
    assert score.failure_reason == ""


def test_score_answer_case_explains_missing_retrieval_and_structured_fact_match():
    structured = AnswerMetricCase(
        case_id="case-4",
        question="What does the figure show?",
        answer="The figure shows a schematic of the baseline objective. [fig-1]",
        expected_facts=(
            "[Figure fig_1] Caption: Schematic of the objective we use in our baseline model. "
            "Nearby Context: In this example, we process a long sentence with multiple labels.",
        ),
        cited_evidence_ids=("fig-1",),
        context_evidence_ids=("fig-1",),
        gold_evidence_ids=("fig-1",),
        retrieved_evidence_ids=("fig-1",),
    )
    missing = AnswerMetricCase(
        case_id="case-5",
        question="What does the formula mean?",
        answer="The context discusses attention instead. [other]",
        expected_facts=("The formula computes a convolution kernel.",),
        cited_evidence_ids=("other",),
        context_evidence_ids=("other",),
        gold_evidence_ids=("eq-1",),
        retrieved_evidence_ids=("other",),
    )

    structured_score = score_answer_case(structured)
    missing_score = score_answer_case(missing)

    assert structured_score.fact_coverage == 1.0
    assert structured_score.answer_success is True
    assert missing_score.failure_reason == RAGFailureReason.MISSING_GOLD_IN_RETRIEVAL.value


def test_score_answer_case_preserves_latex_display_math_for_formula_match():
    case = AnswerMetricCase(
        case_id="case-latex-display",
        question="How is the objective defined?",
        answer=(
            "The objective is\n"
            "\\[\n"
            "\\arg \\max_\\pi \\mathbb{E}_{p \\sim \\mathcal{D}, g \\sim \\pi}[R(g \\mid p)]\n"
            "\\]\n"
            "where prompts come from the dataset and generations come from the policy. [eq-1]"
        ),
        expected_facts=(
            "\\begin{equation}\n"
            "   \\arg \\max _\\pi \\mathbb{E}_{p \\sim \\mathcal{D}, g \\sim \\pi}[R(g \\mid p)]\n"
            "\\end{equation}",
        ),
        cited_evidence_ids=("eq-1",),
        context_evidence_ids=("eq-1",),
        gold_evidence_ids=("eq-1",),
        retrieved_evidence_ids=("eq-1",),
    )

    score = score_answer_case(case)

    assert score.fact_coverage == 1.0
    assert score.answer_success is True


def test_score_answer_case_accepts_equivalent_gold_evidence_support():
    case = AnswerMetricCase(
        case_id="case-equivalent-gold",
        question="How is the Hamiltonian ODE defined?",
        answer="The Hamiltonian ODE is defined as dot y equals J inverse times the Hamiltonian gradient. [para-1]",
        expected_facts=("Hamiltonian ODE is defined as dot y equals J inverse times the Hamiltonian gradient.",),
        cited_evidence_ids=("para-1",),
        context_evidence_ids=("para-1",),
        gold_evidence_ids=("eq-1",),
        equivalent_gold_evidence_ids=("eq-1", "para-1"),
        retrieved_evidence_ids=("para-1",),
    )

    score = score_answer_case(case)

    assert score.answer_success is True
    assert score.failure_reason == ""
    assert score.strict_retrieval_context_coverage == 0.0
    assert score.equivalent_retrieval_context_coverage == 1.0
    assert score.strict_citation_gold_coverage == 0.0
    assert score.equivalent_citation_gold_coverage == 1.0
    assert score.equivalent_gold_supported is True


def test_score_answer_case_uses_canonical_failure_reason_taxonomy():
    context_missing = AnswerMetricCase(
        case_id="case-6",
        question="What does the table show?",
        answer="Only the table is cited. [tbl-1]",
        expected_facts=("The table conclusion is explained in the paragraph.",),
        cited_evidence_ids=("tbl-1",),
        context_evidence_ids=("tbl-1",),
        gold_evidence_ids=("tbl-1", "para-1"),
        retrieved_evidence_ids=("tbl-1", "para-1"),
    )
    citation_missing = AnswerMetricCase(
        case_id="case-7",
        question="What does the table show?",
        answer="The table conclusion is explained in the paragraph. [other]",
        expected_facts=("The table conclusion is explained in the paragraph.",),
        cited_evidence_ids=("other",),
        context_evidence_ids=("tbl-1", "para-1"),
        gold_evidence_ids=("tbl-1", "para-1"),
        retrieved_evidence_ids=("tbl-1", "para-1"),
    )
    abstention_mismatch = AnswerMetricCase(
        case_id="case-8",
        question="What is missing?",
        answer="This paper has enough evidence.",
        expected_abstain=True,
    )

    assert score_answer_case(context_missing).failure_reason == RAGFailureReason.CONTEXT_MISSING_GOLD.value
    assert score_answer_case(citation_missing).failure_reason == RAGFailureReason.CITATION_MISSING_SOURCE.value
    assert score_answer_case(abstention_mismatch).failure_reason == RAGFailureReason.ABSTENTION_EXPECTED.value
