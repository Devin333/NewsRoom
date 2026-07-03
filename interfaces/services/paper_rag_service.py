from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from business.research.application import AskPaperUseCase
from business.research.rag.models import ResearchRetrievalGoal
from business.research.rag.retrieval.paper_retriever import RetrievalRequest
from interfaces.services.paper_rag_factory import build_paper_rag_session, build_research_retriever


class PaperRagApplicationService:
    """Chunk-based RAG service: retrieve context or produce a gated answer."""

    def __init__(
        self,
        *,
        with_reranker: bool = True,
        retriever: Any | None = None,
        session_factory: Callable[..., Any] | None = None,
        ask_use_case: AskPaperUseCase | None = None,
    ) -> None:
        self._with_reranker = with_reranker
        self._retriever = retriever or build_research_retriever(with_reranker=with_reranker)
        self._session_factory = session_factory or build_paper_rag_session
        self._ask_use_case = ask_use_case or AskPaperUseCase()

    def rag_ask(
        self,
        paper_id: str,
        question: str,
        *,
        section_index: int = 0,
        limit: int = 5,
        generate: bool = False,
        gated: bool = True,
        tenant_id: str | None = None,
        user_id: str | None = None,
        memory_namespace: str | None = None,
    ) -> dict[str, Any]:
        if generate and not gated:
            raise ValueError("legacy direct paper RAG answer generation has been removed; use gated Harness generation")
        if generate:
            return self._gated_ask(
                paper_id,
                question,
                section_index=section_index,
                limit=limit,
                tenant_id=tenant_id,
                user_id=user_id,
                memory_namespace=memory_namespace,
            )
        result = self._retriever.retrieve(RetrievalRequest(
            paper_id=paper_id,
            question=question,
            current_section_index=section_index,
            limit=limit,
        ))
        passages, filtered_count = _passages_from_retrieval(result, tenant_id=tenant_id)
        payload: dict[str, Any] = {
            "paper_id": paper_id,
            "question": question,
            "intent": result.intent,
            "passages": passages,
            "metrics": _retrieval_metrics(
                result,
                tenant_id=tenant_id,
                user_id=user_id,
                memory_namespace=memory_namespace,
                tenant_filtered_passage_count=filtered_count,
            ),
        }
        return payload

    def _gated_ask(
        self,
        paper_id: str,
        question: str,
        *,
        section_index: int,
        limit: int,
        tenant_id: str | None,
        user_id: str | None,
        memory_namespace: str | None,
    ) -> dict[str, Any]:
        session = self._session_factory(
            with_reranker=self._with_reranker,
            with_answer_worker=True,
        )
        run_suffix = uuid4().hex[:12]
        goal = self._ask_use_case.build_paper_ask_goal(
            paper_id=paper_id,
            question=question,
            goal_id=f"paper-rag-ask-{run_suffix}",
            tenant_id=tenant_id,
            user_id=user_id,
            memory_namespace=memory_namespace,
        )
        result = session.run(
            goal,
            run_id=f"paper-rag-ask-run-{run_suffix}",
            workflow_id="research.paper_rag_ask",
            step_id="rag_ask",
            session_id=f"paper-rag-ask-session-{run_suffix}",
            current_section_index=section_index,
        )
        return _gated_payload(
            paper_id=paper_id,
            question=question,
            limit=limit,
            goal=goal,
            result=result,
        )

def _passages_from_retrieval(result: Any, *, tenant_id: str | None = None) -> tuple[list[dict[str, Any]], int]:
    visible_chunks = []
    filtered_count = 0
    for chunk in result.child_chunks:
        if _chunk_visible_to_tenant(chunk, tenant_id=tenant_id):
            visible_chunks.append(chunk)
        else:
            filtered_count += 1
    passages = [
        {
            "chunk_id": chunk.chunk_id,
            "section_title": chunk.section_title,
            "chunk_type": chunk.chunk_type,
            "content": chunk.content,
        }
        for chunk in visible_chunks
    ]
    return passages, filtered_count


def _retrieval_metrics(
    result: Any,
    *,
    tenant_id: str | None,
    user_id: str | None,
    memory_namespace: str | None,
    tenant_filtered_passage_count: int,
) -> dict[str, Any]:
    metrics = dict(result.metadata)
    if tenant_id:
        metrics["tenant_id"] = tenant_id
    if user_id:
        metrics["user_id"] = user_id
    if memory_namespace:
        metrics["memory_namespace"] = memory_namespace
    if tenant_filtered_passage_count:
        metrics["tenant_filtered_passage_count"] = tenant_filtered_passage_count
    return metrics


def _chunk_visible_to_tenant(chunk: Any, *, tenant_id: str | None) -> bool:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        return True
    chunk_tenants = _metadata_tenant_ids(getattr(chunk, "metadata", {}))
    return not chunk_tenants or tenant in chunk_tenants


def _metadata_tenant_ids(metadata: Any) -> set[str]:
    if not isinstance(metadata, dict):
        return set()
    values: set[str] = set()
    for key in ("tenant_id", "tenant", "workspace_id"):
        _add_tenant_value(values, metadata.get(key))
    for key in ("tenant_ids", "allowed_tenant_ids"):
        _add_tenant_value(values, metadata.get(key))
    return values


def _add_tenant_value(values: set[str], raw: Any) -> None:
    if raw is None:
        return
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            _add_tenant_value(values, item)
        return
    text = str(raw).strip()
    if text:
        values.add(text)


def _gated_payload(
    *,
    paper_id: str,
    question: str,
    limit: int,
    goal: ResearchRetrievalGoal,
    result: Any,
) -> dict[str, Any]:
    answer = result.answer
    pack = result.context_pack
    return {
        "paper_id": paper_id,
        "question": question,
        "intent": goal.metadata.get("intent", ""),
        "status": result.status.value,
        "generation_mode": "gated_harness",
        "answer": answer.answer_text if answer and not answer.abstained else None,
        "answer_candidate": answer.to_dict() if answer else None,
        "claims": [claim.to_dict() for claim in answer.claims] if answer else [],
        "citations": _citations_from_answer(answer, pack),
        "passages": _passages_from_pack(pack, limit=limit),
        "metrics": _gated_metrics(result, pack),
        "decision": result.decision.to_dict(),
        "gate_results": list(result.decision.gate_results),
        "transcript_id": result.transcript.transcript_id,
        "context_pack": _context_pack_summary(pack),
    }


def _gated_metrics(result: Any, pack: Any | None) -> dict[str, Any]:
    session_metrics = result.metrics.to_dict() if getattr(result, "metrics", None) is not None else {}
    return {
        **session_metrics,
        "context_pack_id": pack.pack_id if pack else session_metrics.get("context_pack_id"),
        "accepted_evidence_count": len(pack.accepted_evidence)
        if pack
        else session_metrics.get("accepted_evidence_count", 0),
        "decision_type": result.decision.decision_type.value,
    }


def _passages_from_pack(pack: Any | None, *, limit: int) -> list[dict[str, Any]]:
    if pack is None:
        return []
    passages = []
    for evidence in pack.accepted_evidence[:limit]:
        passages.append({
            "evidence_id": evidence.evidence_id,
            "chunk_id": evidence.metadata.get("rag_chunk_id", evidence.evidence_id),
            "section_title": evidence.metadata.get("section_title", evidence.title),
            "chunk_type": evidence.metadata.get("chunk_type", evidence.evidence_type),
            "content": evidence.summary,
            "source_locator": evidence.metadata.get("source_locator") or evidence.source_ref,
        })
    return passages


def _citations_from_answer(answer: Any | None, pack: Any | None) -> list[dict[str, Any]]:
    if answer is None or pack is None:
        return []
    by_id = {item.evidence_id: item for item in pack.accepted_evidence}
    citations = []
    for evidence_id in answer.cited_evidence_ids:
        evidence = by_id.get(evidence_id)
        citations.append({
            "evidence_id": evidence_id,
            "chunk_id": evidence.metadata.get("rag_chunk_id", evidence_id) if evidence else evidence_id,
            "span_refs": _citation_span_refs(answer, evidence_id, evidence),
            "source_locator": (
                evidence.metadata.get("source_locator")
                or evidence.source_ref
                if evidence
                else ""
            ),
            "title": evidence.title if evidence else "",
        })
    return citations


def _citation_span_refs(answer: Any, evidence_id: str, evidence: Any | None) -> list[str]:
    available = set(evidence.span_refs) if evidence else None
    span_refs: list[str] = []
    seen: set[str] = set()
    for claim in answer.claims:
        if evidence_id not in claim.evidence_ids:
            continue
        for span_ref in claim.span_refs:
            if available is not None and span_ref not in available:
                continue
            if span_ref in seen:
                continue
            seen.add(span_ref)
            span_refs.append(span_ref)
    return span_refs


def _context_pack_summary(pack: Any | None) -> dict[str, Any] | None:
    if pack is None:
        return None
    return {
        "pack_id": pack.pack_id,
        "accepted_evidence_ids": [item.evidence_id for item in pack.accepted_evidence],
        "rejected_evidence_ids": [item.evidence_id for item in pack.rejected_evidence],
        "gap_report": pack.gap_report,
        "assembly_summary": pack.assembly_summary,
    }


__all__ = ["PaperRagApplicationService"]
