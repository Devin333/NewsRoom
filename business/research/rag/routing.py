from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

QueryIntent = Literal[
    "concept_method",
    "numerical_result",
    "contribution",
    "comparison",
    "figure_query",
    "formula_query",
]

_INTENT_SIGNALS: list[tuple[QueryIntent, list[str]]] = [
    ("figure_query",     ["图", "figure", "fig", "图表"]),
    ("formula_query",    ["公式", "formula", "equation", "符号", "变量"]),
    ("comparison",       ["相比", "对比", "compared to", "versus", " vs ", "prior work", "baseline", "相关工作"]),
    ("numerical_result", ["准确率", "f1", "bleu", "rouge", "outperform", "accuracy", "多少", "几%", "score"]),
    ("contribution",     ["贡献", "contribution", "novelty", "propose", "提出", "创新", "what does this paper"]),
    ("concept_method",   ["如何", "怎么", "how", "what is", "why", "method", "approach", "architecture"]),
]

_FIGURE_ID_RE = re.compile(r"图\s*(\w+)|[Ff]ig(?:ure)?[.s]?\s*(\w+)")


@dataclass
class RetrievalRoute:
    intent: QueryIntent
    section_role_filter: list[str] = field(default_factory=list)
    chunk_type_filter: list[str] = field(default_factory=list)
    figure_id: str = ""
    use_propositions: bool = False
    prefer_abstract: bool = False
    extra_filters: dict[str, Any] = field(default_factory=dict)


def classify_query_intent(question: str) -> QueryIntent:
    q = question.lower()
    for intent, keywords in _INTENT_SIGNALS:
        if any(kw in q for kw in keywords):
            return intent
    return "concept_method"


def build_retrieval_route(question: str) -> RetrievalRoute:
    """Map a user question to retrieval path (PRD §7)."""
    intent = classify_query_intent(question)

    if intent == "figure_query":
        return RetrievalRoute(
            intent=intent,
            chunk_type_filter=["figure"],
            extra_filters={"chunk_type": "figure"},
        )

    if intent == "formula_query":
        return RetrievalRoute(
            intent=intent,
            extra_filters={"has_formula": True},
        )

    if intent == "numerical_result":
        return RetrievalRoute(
            intent=intent,
            section_role_filter=["experiment"],
            use_propositions=True,
        )

    if intent == "contribution":
        return RetrievalRoute(
            intent=intent,
            chunk_type_filter=["abstract", "paragraph"],
            prefer_abstract=True,
            use_propositions=True,
        )

    if intent == "comparison":
        return RetrievalRoute(
            intent=intent,
            section_role_filter=["related_work"],
            use_propositions=True,
        )

    # concept_method: default
    return RetrievalRoute(
        intent=intent,
        section_role_filter=["method"],
    )


__all__ = ["QueryIntent", "RetrievalRoute", "build_retrieval_route", "classify_query_intent"]
