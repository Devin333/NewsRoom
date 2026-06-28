from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from framework.rag.retrieval import (
    QueryIntentRule,
    build_query_intent_rules,
    classify_query_intent_by_rules,
)

QueryIntent = Literal[
    "citation_query",
    "concept_method",
    "numerical_result",
    "contribution",
    "comparison",
    "figure_query",
    "table_query",
    "formula_query",
]

_INTENT_SIGNALS: tuple[QueryIntentRule, ...] = build_query_intent_rules([
    ("numerical_result", [
        "\u5b9e\u9a8c\u7ed3\u679c",
        "\u7ed3\u679c",
        "\u8868\u660e",
        "experiment results",
        "results show",
    ]),
    ("table_query",      ["table", "tab.", "tab ", "row", "column"]),
    ("formula_query",    ["formula", "equation", "eq.", " eq ", "latex", "symbol", "variable"]),
    ("figure_query",     ["图", "figure", "fig", "图表"]),
    ("formula_query",    ["公式", "formula", "equation", "符号", "变量"]),
    ("comparison",       ["相比", "对比", "compared to", "versus", " vs ", "prior work", "baseline", "相关工作"]),
    ("numerical_result", ["准确率", "f1", "bleu", "rouge", "outperform", "accuracy", "多少", "几%", "score"]),
    ("contribution",     ["贡献", "contribution", "novelty", "propose", "提出", "创新", "what does this paper"]),
    ("concept_method",   ["如何", "怎么", "how", "what is", "why", "method", "approach", "architecture"]),
])

_FIGURE_ID_RE = re.compile(r"图\s*(\w+)|[Ff]ig(?:ure)?[.s]?\s*(\w+)")
_CITATION_QUERY_RE = re.compile(
    r"\b(?:which|what)\s+evidence\s+supports\s+(?:the\s+)?claim\b|"
    r"\bsupport(?:ing)?\s+evidence\s+for\s+(?:the\s+)?claim\b",
    flags=re.IGNORECASE,
)


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
    if _CITATION_QUERY_RE.search(str(question or "")):
        return "citation_query"
    intent = classify_query_intent_by_rules(
        question,
        _INTENT_SIGNALS,
        default_intent="concept_method",
    )
    return cast(QueryIntent, intent)


def build_retrieval_route(question: str) -> RetrievalRoute:
    """Map a user question to retrieval path (PRD §7)."""
    intent = classify_query_intent(question)

    if intent == "citation_query":
        return RetrievalRoute(
            intent=intent,
            chunk_type_filter=["abstract", "paragraph"],
            use_propositions=True,
        )

    if intent == "figure_query":
        return RetrievalRoute(
            intent=intent,
            chunk_type_filter=["figure"],
            extra_filters={"chunk_type": "figure"},
        )

    if intent == "table_query":
        return RetrievalRoute(
            intent=intent,
            chunk_type_filter=["table"],
            extra_filters={"chunk_type": "table"},
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
