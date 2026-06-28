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


def test_blind_semantic_citation_grounding_question_routes_to_citation() -> None:
    question = "Which passage grounds the paper's claim about vectors, objective, and examples?"

    route = build_retrieval_route(question)

    assert classify_query_intent(question) == "citation_query"
    assert route.intent == "citation_query"
    assert route.recall_routes == ("citation_claim", "abstract_body")


def test_explicit_figure_question_routes_before_formula_symbol_keywords() -> None:
    question = (
        "What does Figure 1, captioned Chain-of-thought prompting enables large "
        "language models to tackle complex arithmetic, commonsense, and symbolic "
        "reasoning tasks, show?"
    )

    route = build_retrieval_route(question)

    assert classify_query_intent(question) == "figure_query"
    assert route.intent == "figure_query"
    assert route.extra_filters == {"chunk_type": "figure"}


@pytest.mark.parametrize(
    ("question", "intent", "routes"),
    [
        (
            "What quantitative evidence do the reported experiments provide about BLEU performance?",
            "numerical_result",
            ("table_chunks", "result_paragraphs", "conclusion_context"),
        ),
        (
            "What visual evidence explains the architecture diagram and example images?",
            "figure_query",
            ("figure_chunks", "caption_fields", "referenced_context"),
        ),
        (
            "How does the paper define the mathematical relation for the loss objective?",
            "formula_query",
            ("formula_chunks", "equation_fields", "formula_context"),
        ),
    ],
)
def test_blind_semantic_natural_questions_route_to_v2_plans(
    question: str,
    intent: str,
    routes: tuple[str, ...],
) -> None:
    route = build_retrieval_route(question)

    assert classify_query_intent(question) == intent
    assert route.intent == intent
    assert route.recall_routes == routes


def test_numerical_result_uses_table_and_paragraph_candidate_routes() -> None:
    route = build_retrieval_route("What do the reported experiments suggest overall?")

    assert route.intent == "numerical_result"
    assert route.candidate_filter_groups == (
        {"chunk_type": "table"},
        {"chunk_type": "paragraph"},
    )
