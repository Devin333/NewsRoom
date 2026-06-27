from __future__ import annotations

import math
from typing import Mapping


def intent_allowed(intent: str, allowed_intents: tuple[str, ...] = ()) -> bool:
    return not allowed_intents or intent in allowed_intents


def position_decay_score(
    *,
    section_index: int,
    current_index: int,
    alpha: float,
    sigma: float,
) -> float:
    if alpha <= 0.0:
        return 0.0
    if sigma <= 0.0:
        return float(alpha) if section_index == current_index else 0.0
    return float(alpha) * math.exp(-abs(int(section_index) - int(current_index)) / float(sigma))


def intent_budget(
    intent: str,
    *,
    intent_budgets: Mapping[str, tuple[int, int]],
    default_budget: tuple[int, int],
    max_chunks: int,
    max_tokens: int,
) -> tuple[int, int]:
    count, tokens = intent_budgets.get(intent, default_budget)
    return (
        max(0, min(int(max_chunks), int(count))),
        max(0, min(int(max_tokens), int(tokens))),
    )


__all__ = ["intent_allowed", "intent_budget", "position_decay_score"]
