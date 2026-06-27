from __future__ import annotations

from typing import Any

from framework.harness.rag.models import EvidenceCandidate
from framework.rag.core import RAGEvidence


def evidence_candidate_from_rag_evidence(
    evidence: RAGEvidence,
    *,
    evidence_type: str = "rag_evidence",
    title: str | None = None,
) -> EvidenceCandidate:
    source_ref = _source_ref(evidence)
    metadata: dict[str, Any] = {
        **dict(evidence.metadata),
        "rag_document_id": evidence.document_id,
        "rag_chunk_id": evidence.chunk_id,
        "rag_score": evidence.score,
        "rag_score_breakdown": evidence.score_breakdown.to_dict(),
    }
    if evidence.source_locator is not None:
        metadata["rag_source_locator"] = evidence.source_locator.to_dict()
    return EvidenceCandidate(
        evidence_id=evidence.evidence_id,
        title=title or str(evidence.metadata.get("title") or evidence.metadata.get("section_title") or evidence.chunk_id),
        summary=evidence.text[:1200],
        source_ref=source_ref,
        span_refs=(source_ref,),
        evidence_type=evidence_type,
        confidence=_confidence(evidence.score),
        freshness=str(evidence.metadata.get("freshness") or "unknown"),
        lineage=(evidence.document_id,),
        artifact_refs=_artifact_refs(evidence.metadata),
        metadata=metadata,
    )


def _source_ref(evidence: RAGEvidence) -> str:
    if evidence.source_locator is not None:
        return evidence.source_locator.raw_locator or evidence.source_locator.source_id
    source_locator = str(evidence.metadata.get("source_locator") or "")
    if source_locator:
        return source_locator
    return f"rag://{evidence.document_id}/{evidence.chunk_id}"


def _confidence(score: float) -> float:
    return max(0.0, min(float(score), 1.0))


def _artifact_refs(metadata: dict[str, Any]) -> tuple[str, ...]:
    raw = metadata.get("artifact_refs") or metadata.get("artifact_ref") or ()
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (tuple, list)):
        return ()
    return tuple(str(ref) for ref in raw if str(ref).strip())


__all__ = ["evidence_candidate_from_rag_evidence"]
