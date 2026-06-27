from __future__ import annotations

from collections.abc import Callable, Iterable

from framework.rag.core import RAGEvidence


def order_evidence(evidence: Iterable[RAGEvidence], *, reverse: bool = True) -> list[RAGEvidence]:
    return sorted(evidence, key=lambda item: item.score, reverse=reverse)


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


__all__ = ["dedupe_evidence", "order_evidence"]
