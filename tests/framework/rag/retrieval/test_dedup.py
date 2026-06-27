from __future__ import annotations

from framework.rag.core import RAGEvidence
from framework.rag.retrieval import dedupe_evidence, order_evidence


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


def test_order_evidence_sorts_by_score_descending():
    out = order_evidence([
        _evidence("ev-1", "chunk-1", 0.2),
        _evidence("ev-2", "chunk-2", 0.9),
    ])

    assert [item.evidence_id for item in out] == ["ev-2", "ev-1"]
