from __future__ import annotations

from framework.rag.core import RAGEvidence
from framework.rag.retrieval import dedupe_by_key, dedupe_evidence, order_evidence


def _evidence(evidence_id: str, chunk_id: str, score: float) -> RAGEvidence:
    return RAGEvidence(
        evidence_id=evidence_id,
        chunk_id=chunk_id,
        document_id="doc-1",
        text=f"Evidence {evidence_id}",
        score=score,
    )


def test_dedupe_evidence_keeps_highest_scoring_duplicate():
    out = dedupe_evidence([
        _evidence("ev-low", "chunk-1", 0.2),
        _evidence("ev-other", "chunk-2", 0.5),
        _evidence("ev-high", "chunk-1", 0.9),
    ])

    assert [item.evidence_id for item in out] == ["ev-high", "ev-other"]


def test_dedupe_by_key_keeps_first_item_for_each_key():
    items = [
        {"chunk_id": "chunk-1", "rank": 1},
        {"chunk_id": "chunk-2", "rank": 2},
        {"chunk_id": "chunk-1", "rank": 3},
    ]

    out = dedupe_by_key(items, key=lambda item: item["chunk_id"])

    assert out == [
        {"chunk_id": "chunk-1", "rank": 1},
        {"chunk_id": "chunk-2", "rank": 2},
    ]


def test_order_evidence_sorts_by_score_descending():
    out = order_evidence([
        _evidence("ev-1", "chunk-1", 0.2),
        _evidence("ev-2", "chunk-2", 0.9),
    ])

    assert [item.evidence_id for item in out] == ["ev-2", "ev-1"]
