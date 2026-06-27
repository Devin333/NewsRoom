from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class QueryIntentRule:
    intent: str
    signals: tuple[str, ...]

    def __post_init__(self) -> None:
        intent = str(self.intent or "").strip()
        if not intent:
            raise ValueError("intent is required")
        signals = tuple(str(signal).casefold() for signal in self.signals if str(signal).strip())
        if not signals:
            raise ValueError("signals are required")
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "signals", signals)


def classify_query_intent_by_rules(
    query: str,
    rules: Sequence[QueryIntentRule],
    *,
    default_intent: str,
) -> str:
    text = str(query or "").casefold()
    fallback = str(default_intent or "").strip()
    if not fallback:
        raise ValueError("default_intent is required")
    for rule in rules:
        if any(signal in text for signal in rule.signals):
            return rule.intent
    return fallback


def build_query_intent_rules(raw_rules: Sequence[tuple[str, Sequence[str]]]) -> tuple[QueryIntentRule, ...]:
    return tuple(QueryIntentRule(intent=intent, signals=tuple(signals)) for intent, signals in raw_rules)


__all__ = [
    "QueryIntentRule",
    "build_query_intent_rules",
    "classify_query_intent_by_rules",
]
