from __future__ import annotations

from business.research.rag.answer_eval import EvidenceAnswerEvaluator, EvidenceAnswerSample
from business.research.rag.evidence_eval import EvidenceQAPair


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
    )

    result = EvidenceAnswerEvaluator().evaluate([sample])
    score = result.scores[0]

    assert score.fact_coverage == 1.0
    assert score.citation_grounding == 1.0
    assert score.source_locator_grounding == 1.0
    assert score.answer_success is True
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
    )

    score = EvidenceAnswerEvaluator().score(sample)

    assert score.fact_coverage == 0.5
    assert score.citation_grounding == 0.5
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
        answer="The paper does not discuss that, and there is not enough evidence to answer.",
    )
    bad = EvidenceAnswerSample(
        pair=pair,
        answer="Yes, it uses the unrelated future model.",
    )

    result = EvidenceAnswerEvaluator().evaluate([good, bad])

    assert [score.abstention_correct for score in result.scores] == [1.0, 0.0]
    assert result.abstention_accuracy() == 0.5
    assert result.success_rate() == 0.5


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
