from __future__ import annotations

import pytest

from framework.rag.retrieval import (
    QueryIntentRule,
    build_query_intent_rules,
    classify_query_intent_by_rules,
)


def test_classify_query_intent_by_rules_returns_first_matching_intent():
    rules = build_query_intent_rules([
        ("result", ("accuracy", "score")),
        ("method", ("architecture", "approach")),
    ])

    assert classify_query_intent_by_rules(
        "Which architecture gets the best score?",
        rules,
        default_intent="general",
    ) == "result"


def test_classify_query_intent_by_rules_uses_default_when_no_rule_matches():
    rules = (QueryIntentRule(intent="figure", signals=("figure",)),)

    assert classify_query_intent_by_rules(
        "Summarize the idea",
        rules,
        default_intent="general",
    ) == "general"


def test_query_intent_rule_requires_intent_and_signals():
    with pytest.raises(ValueError, match="intent is required"):
        QueryIntentRule(intent="", signals=("x",))

    with pytest.raises(ValueError, match="signals are required"):
        QueryIntentRule(intent="x", signals=())
