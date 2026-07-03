from __future__ import annotations

import asyncio
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
    ) -> dict[str, Any]:
        if generate and gated:
            return self._gated_ask(
                paper_id,
                question,
                section_index=section_index,
                limit=limit,
            )
        result = self._retriever.retrieve(RetrievalRequest(
            paper_id=paper_id,
            question=question,
            current_section_index=section_index,
            limit=limit,
        ))
        payload: dict[str, Any] = {
            "paper_id": paper_id,
            "question": question,
            "intent": result.intent,
            "passages": _passages_from_retrieval(result),
            "metrics": result.metadata,
        }
        if generate:
            payload["answer"] = self._generate(question, result)
            payload["generation_mode"] = "legacy_direct"
            payload["status"] = "legacy_direct_answered" if str(payload["answer"]).strip() else "legacy_direct_empty"
        return payload

    def _gated_ask(
        self,
        paper_id: str,
        question: str,
        *,
        section_index: int,
        limit: int,
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

    def _generate(self, question: str, retrieval: Any) -> str:
        from business.research.application.llm_client import build_unity_llm_call
        from business.research.rag.retrieval.paper_answer_generator import AnswerGenerator

        generator = AnswerGenerator(build_unity_llm_call(max_tokens=600))
        return asyncio.run(generator.generate(question, retrieval)).answer


def _passages_from_retrieval(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk.chunk_id,
            "section_title": chunk.section_title,
            "chunk_type": chunk.chunk_type,
            "content": chunk.content,
        }
        for chunk in result.child_chunks
    ]


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
        "metrics": {
            "context_pack_id": pack.pack_id if pack else None,
            "accepted_evidence_count": len(pack.accepted_evidence) if pack else 0,
            "decision_type": result.decision.decision_type.value,
        },
        "decision": result.decision.to_dict(),
        "gate_results": list(result.decision.gate_results),
        "transcript_id": result.transcript.transcript_id,
        "context_pack": _context_pack_summary(pack),
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
            "source_locator": (
                evidence.metadata.get("source_locator")
                or evidence.source_ref
                if evidence
                else ""
            ),
            "title": evidence.title if evidence else "",
        })
    return citations


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
