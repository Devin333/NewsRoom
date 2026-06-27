from __future__ import annotations

from framework.rag.retrieval import score_fields


def test_field_score_reports_best_matching_field_and_scores():
    result = score_fields(
        "What does the result table show?",
        {
            "body": "The method trains a model.",
            "caption": "Result table showing accuracy and loss.",
            "equation": "y = Wx",
        },
        field_weights={"caption": 2.0},
    )

    assert result.best_field == "caption"
    assert result.field_scores["caption"] > result.field_scores["body"]
    assert "result" in result.query_terms


def test_field_score_handles_empty_query_or_fields():
    assert score_fields("", {"body": "text"}).field_scores == {}
    assert score_fields("query", {"body": ""}).field_scores == {}
