from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from threading import Thread
from typing import Any
from uuid import uuid4

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.contracts import RetrievalResult
from business.research.rag.retrieval.paper_answer_generator import AnswerGenerator, GeneratedAnswer
from business.research.rag.retrieval.paper_policy import classify_query_intent
from framework.harness.rag.models import AnswerClaim, GroundedAnswerCandidate, RAGContextPack


@dataclass(frozen=True)
class _ProjectedContext:
    retrieval: RetrievalResult
    chunk_to_evidence_id: dict[str, str]
    evidence_id_to_span_refs: dict[str, tuple[str, ...]]


class PaperAnswerWorker:
    """Projects verified Paper RAG context packs into grounded answer candidates."""

    def __init__(self, generator: AnswerGenerator) -> None:
        self._generator = generator

    def generate_answer(self, *, question: str, pack: RAGContextPack) -> GroundedAnswerCandidate:
        projected = _project_context_pack(pack, question=question)
        if projected is None:
            return _abstention(
                question,
                reason="context pack lacks paper_chunk metadata",
                context_pack_id=pack.pack_id,
            )

        generated = _run_async(self._generator.generate(question, projected.retrieval))
        cited_evidence_ids = _map_chunk_ids(generated.context_chunk_ids, projected.chunk_to_evidence_id)
        if not generated.answer.strip():
            return _abstention(
                question,
                reason="answer generator returned empty answer",
                context_pack_id=pack.pack_id,
                metadata={"generated_answer": generated.to_dict()},
            )
        if _looks_like_context_abstention(generated.answer):
            return _abstention(
                question,
                reason="answer generator reported insufficient context",
                context_pack_id=pack.pack_id,
                metadata={"generated_answer": generated.to_dict()},
            )

        return GroundedAnswerCandidate(
            answer_id=f"paper-answer-{uuid4().hex[:12]}",
            question=question,
            answer_text=generated.answer,
            cited_evidence_ids=tuple(cited_evidence_ids),
            claims=(_conservative_claim(generated, cited_evidence_ids, projected.evidence_id_to_span_refs),),
            metadata={
                "worker": "paper_answer_worker",
                "context_pack_id": pack.pack_id,
                "context_chunk_ids": list(generated.context_chunk_ids),
                "chunk_to_evidence_id": dict(projected.chunk_to_evidence_id),
                "evidence_id_to_span_refs": {
                    evidence_id: list(span_refs)
                    for evidence_id, span_refs in projected.evidence_id_to_span_refs.items()
                },
                "claims_degraded": True,
                "generated_answer_metadata": dict(generated.context_metadata),
            },
        )


def _project_context_pack(pack: RAGContextPack, *, question: str) -> _ProjectedContext | None:
    chunks: list[PaperChunk] = []
    chunk_to_evidence_id: dict[str, str] = {}
    evidence_id_to_span_refs: dict[str, tuple[str, ...]] = {}
    for evidence in pack.accepted_evidence:
        chunk = _paper_chunk_from_metadata(evidence.metadata.get("paper_chunk"))
        if chunk is None:
            chunk = _paper_chunk_from_evidence(evidence)
        if chunk is None:
            continue
        chunks.append(chunk)
        chunk_to_evidence_id.setdefault(chunk.chunk_id, evidence.evidence_id)
        evidence_id_to_span_refs.setdefault(evidence.evidence_id, tuple(evidence.span_refs))

    chunks = _dedupe_chunks(chunks)
    if not chunks:
        return None

    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=chunks,
        ref_chunks=[],
        intent=classify_query_intent(question),
        metadata={
            "source": "rag_context_pack",
            "context_pack_id": pack.pack_id,
            "accepted_evidence_ids": [item.evidence_id for item in pack.accepted_evidence],
        },
    )
    return _ProjectedContext(
        retrieval=retrieval,
        chunk_to_evidence_id=chunk_to_evidence_id,
        evidence_id_to_span_refs=evidence_id_to_span_refs,
    )


def _paper_chunk_from_metadata(raw: Any) -> PaperChunk | None:
    if isinstance(raw, PaperChunk):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return PaperChunk(**raw)
    except Exception:
        return None


def _paper_chunk_from_evidence_metadata(metadata: dict[str, Any]) -> PaperChunk | None:
    chunk_id = str(metadata.get("rag_chunk_id") or metadata.get("chunk_id") or "").strip()
    paper_id = str(metadata.get("paper_id") or metadata.get("rag_document_id") or "").strip()
    content = str(metadata.get("content") or metadata.get("text") or "").strip()
    if not chunk_id or not paper_id or not content:
        return None
    try:
        return PaperChunk(
            chunk_id=chunk_id,
            paper_id=paper_id,
            parse_source=str(metadata.get("parse_source") or "pymupdf"),
            structure_detected=bool(metadata.get("structure_detected", True)),
            chunk_type=str(metadata.get("chunk_type") or "paragraph"),
            parent_chunk_id=metadata.get("parent_chunk_id"),
            section_title=str(metadata.get("section_title") or ""),
            section_role=_text_list(metadata.get("section_role")),
            section_index=int(metadata.get("section_index") or 0),
            has_formula=bool(metadata.get("has_formula", False)),
            formula_latex=str(metadata.get("formula_latex") or ""),
            formula_description=str(metadata.get("formula_description") or ""),
            has_figure=bool(metadata.get("has_figure", False)),
            figure_id=str(metadata.get("figure_id") or ""),
            has_table=bool(metadata.get("has_table", False)),
            references=_text_list(metadata.get("references")),
            propositions_generated=bool(metadata.get("propositions_generated", False)),
            proposition_quality=str(metadata.get("proposition_quality") or "unknown"),
            content=content,
            metadata=dict(metadata),
        )
    except Exception:
        return None


def _paper_chunk_from_evidence(evidence: Any) -> PaperChunk | None:
    metadata = dict(getattr(evidence, "metadata", {}) or {})
    if "content" not in metadata and "text" not in metadata:
        metadata["content"] = str(getattr(evidence, "summary", "") or "")
    return _paper_chunk_from_evidence_metadata(metadata)


def _map_chunk_ids(chunk_ids: list[str], mapping: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for chunk_id in chunk_ids:
        evidence_id = mapping.get(chunk_id)
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        out.append(evidence_id)
    return out


def _text_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, (list, tuple, set)):
        return [str(item) for item in raw if str(item).strip()]
    return []


def _conservative_claim(
    generated: GeneratedAnswer,
    cited_evidence_ids: list[str],
    evidence_id_to_span_refs: dict[str, tuple[str, ...]],
) -> AnswerClaim:
    return AnswerClaim(
        claim_id="claim-1",
        text=generated.answer.strip(),
        evidence_ids=tuple(cited_evidence_ids),
        span_refs=_claim_span_refs(cited_evidence_ids, evidence_id_to_span_refs),
    )


def _claim_span_refs(
    cited_evidence_ids: list[str],
    evidence_id_to_span_refs: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for evidence_id in cited_evidence_ids:
        for span_ref in evidence_id_to_span_refs.get(evidence_id, ()):
            if span_ref in seen:
                continue
            seen.add(span_ref)
            out.append(span_ref)
    return tuple(out)


def _looks_like_context_abstention(answer: str) -> bool:
    text = " ".join(str(answer or "").casefold().split())
    if not text:
        return True
    direct_markers = (
        "cannot determine",
        "cannot answer",
        "insufficient evidence",
        "not enough evidence",
        "not in the provided context",
        "not available from the passages",
        "provided context does not mention",
        "provided passages do not mention",
        "context does not mention",
        "no evidence",
    )
    if any(marker in text for marker in direct_markers):
        return True
    context_anchors = (
        "provided context",
        "provided passages",
        "the context",
        "the passages",
        "context passages",
    )
    absence_markers = (
        "does not contain",
        "do not contain",
        "does not discuss",
        "do not discuss",
        "does not mention",
        "do not mention",
        "does not include",
        "do not include",
        "does not provide",
        "do not provide",
        "does not address",
        "do not address",
        "does not report",
        "do not report",
        "not contain",
        "not discuss",
        "not mention",
        "not include",
        "not provide",
        "not address",
        "not report",
    )
    if any(anchor in text for anchor in context_anchors) and any(marker in text for marker in absence_markers):
        return True
    return bool(re.search(r"\b(no|not enough|insufficient)\s+(evidence|information)\b", text))


def _abstention(
    question: str,
    *,
    reason: str,
    context_pack_id: str,
    metadata: dict[str, Any] | None = None,
) -> GroundedAnswerCandidate:
    return GroundedAnswerCandidate(
        answer_id=f"paper-answer-abstain-{uuid4().hex[:12]}",
        question=question,
        answer_text="",
        cited_evidence_ids=(),
        claims=(),
        abstained=True,
        metadata={
            "worker": "paper_answer_worker",
            "context_pack_id": context_pack_id,
            "abstention_reason": reason,
            **dict(metadata or {}),
        },
    )


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    seen: set[str] = set()
    out: list[PaperChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        out.append(chunk)
    return out


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result["error"] = exc

    thread = Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


__all__ = ["PaperAnswerWorker"]
