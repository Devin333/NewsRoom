from __future__ import annotations

import pytest

from business.research.rag.routing import build_retrieval_route, classify_query_intent


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
