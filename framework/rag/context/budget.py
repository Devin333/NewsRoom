from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from framework.rag.core import RAGEvidence


@dataclass(frozen=True)
class ContextBudget:
    max_items: int | None = None
    max_text_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_items is not None and self.max_items <= 0:
            raise ValueError("max_items must be greater than zero")
        if self.max_text_chars is not None and self.max_text_chars <= 0:
            raise ValueError("max_text_chars must be greater than zero")


def trim_evidence_to_budget(evidence: Iterable[RAGEvidence], budget: ContextBudget) -> list[RAGEvidence]:
    selected: list[RAGEvidence] = []
    used_chars = 0
    for item in evidence:
        if budget.max_items is not None and len(selected) >= budget.max_items:
            break
        next_chars = used_chars + len(item.text)
        if budget.max_text_chars is not None and next_chars > budget.max_text_chars:
            continue
        selected.append(item)
        used_chars = next_chars
    return selected


__all__ = ["ContextBudget", "trim_evidence_to_budget"]
