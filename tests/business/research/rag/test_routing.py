from __future__ import annotations

import pytest

from business.research.rag.retrieval.paper_policy import build_retrieval_route, classify_query_intent


@pytest.mark.parametrize(
    "question",
    [
        "What does Equation 2 mean in this paper?",
        "What does Eq. 3 mean?",
        "What does this latex expression mean?",
        "Which variable does this symbol represent?",
    ],
)
def test_formula_questions_route_to_formula_query(question: str) -> None:
    assert classify_query_intent(question) == "formula_query"

    route = build_retrieval_route(question)

    assert route.intent == "formula_query"
    assert route.extra_filters == {"has_formula": True}


def test_citation_questions_route_before_table_keywords() -> None:
    question = (
        "Which evidence supports the claim: Large language models pre-trained on "
        "web-scale datasets show strong zero-shot and few-shot generalization?"
    )

    route = build_retrieval_route(question)

    assert classify_query_intent(question) == "citation_query"
    assert route.intent == "citation_query"
    assert route.extra_filters == {}
    assert route.chunk_type_filter == ["abstract", "paragraph"]
