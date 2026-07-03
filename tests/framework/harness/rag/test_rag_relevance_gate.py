from __future__ import annotations

from framework.harness.rag.models import EvidenceCandidate
from framework.harness.rag.relevance import RAGRelevanceGate


def test_rag_relevance_gate_passes_when_all_scores_meet_threshold() -> None:
    gate = RAGRelevanceGate(default_threshold=0.3)
    result = gate.evaluate("question", (_candidate("method"),), (0.31,))

    assert result.passed is True
    assert result.details["low_relevance"] == []


def test_rag_relevance_gate_reports_low_relevance_evidence() -> None:
    gate = RAGRelevanceGate(default_threshold=0.3)
    result = gate.evaluate("question", (_candidate("method"), _candidate("experiment", evidence_id="ev-2")), (0.2, 0.7))

    assert result.passed is False
    assert result.details["threshold"] == 0.3
    assert result.details["low_relevance"] == [{
        "evidence_id": "ev-1",
        "evidence_type": "method",
        "score": 0.2,
    }]


def test_rag_relevance_gate_fails_on_score_count_mismatch() -> None:
    gate = RAGRelevanceGate(default_threshold=0.3)
    result = gate.evaluate("question", (_candidate("method"), _candidate("experiment", evidence_id="ev-2")), (0.8,))

    assert result.passed is False
    assert result.details["score_count_mismatch"] is True


def _candidate(evidence_type: str, *, evidence_id: str = "ev-1") -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=evidence_id,
        title=evidence_id,
        summary="summary",
        source_ref=f"source://{evidence_id}",
        span_refs=(f"source://{evidence_id}#span",),
        evidence_type=evidence_type,
        confidence=0.9,
        lineage=("retrieval.fake",),
    )
