from __future__ import annotations

from framework.rag.evaluation import MetricValue, RAGEvaluationReport, RAGFailureReason, RAGScorecard


def test_scorecard_and_report_serialize_metrics_and_failure_reasons():
    scorecard = RAGScorecard(
        run_id="run-1",
        metrics=(MetricValue("hit_at_10", 0.8),),
        failure_reasons=(RAGFailureReason.LOW_RANK_GOLD,),
        metadata={"split": "test"},
    )
    report = RAGEvaluationReport(title="RAG Eval", scorecard=scorecard)

    payload = report.to_dict()
    markdown = report.to_markdown()

    assert payload["scorecard"]["failure_reasons"] == ["low_rank_gold"]
    assert payload["scorecard"]["metrics"][0]["name"] == "hit_at_10"
    assert "- hit_at_10: `0.800`" in markdown
    assert "- low_rank_gold" in markdown


def test_scorecard_normalizes_legacy_failure_reason_strings():
    scorecard = RAGScorecard(
        run_id="run-1",
        failure_reasons=("missing_gold_in_llm_context", "unexpected_abstention"),
    )

    assert [reason.value for reason in scorecard.failure_reasons] == [
        "context_missing_gold",
        "abstention_expected",
    ]
