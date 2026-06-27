from __future__ import annotations

from framework.rag.evaluation import AnswerMetricCase, evaluate_answer_case


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
