from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from framework.rag.core import RAGEvidence

T = TypeVar("T")


def order_evidence(evidence: Iterable[RAGEvidence], *, reverse: bool = True) -> list[RAGEvidence]:
    return sorted(evidence, key=lambda item: item.score, reverse=reverse)


def dedupe_by_key(items: Iterable[T], *, key: Callable[[T], str]) -> list[T]:
    seen: set[str] = set()
    out: list[T] = []
    for item in items:
        dedupe_key = str(key(item))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(item)
    return out


def dedupe_evidence(
    evidence: Iterable[RAGEvidence],
    *,
    key: Callable[[RAGEvidence], str] | None = None,
) -> list[RAGEvidence]:
    key_fn = key or (lambda item: item.chunk_id)
    winners: dict[str, RAGEvidence] = {}
    order: list[str] = []
    for item in evidence:
        dedupe_key = str(key_fn(item))
        current = winners.get(dedupe_key)
        if current is None:
            winners[dedupe_key] = item
            order.append(dedupe_key)
            continue
        if item.score > current.score:
            winners[dedupe_key] = item
    return [winners[dedupe_key] for dedupe_key in order]


__all__ = ["dedupe_by_key", "dedupe_evidence", "order_evidence"]
