from __future__ import annotations

import asyncio
from typing import Any

from interfaces.services.paper_rag_factory import build_research_retriever
from business.research.rag.retrieval.paper_retriever import RetrievalRequest


class PaperRagApplicationService:
    """Chunk-based RAG service: retrieve (reranked) + optional grounded answer.

    Distinct from the legacy AskPaperUseCase — this drives the chunk pipeline
    (vector recall → cross-encoder rerank → position-aware → parent expansion).
    """

    def __init__(self, *, with_reranker: bool = True) -> None:
        # retriever holds the resident reranker singleton; built once per service.
        self._retriever = build_research_retriever(with_reranker=with_reranker)

    def rag_ask(
        self,
        paper_id: str,
        question: str,
        *,
        section_index: int = 0,
        limit: int = 5,
        generate: bool = False,
    ) -> dict[str, Any]:
        result = self._retriever.retrieve(RetrievalRequest(
            paper_id=paper_id,
            question=question,
            current_section_index=section_index,
            limit=limit,
        ))
        passages = [
            {
                "chunk_id": c.chunk_id,
                "section_title": c.section_title,
                "chunk_type": c.chunk_type,
                "content": c.content,
            }
            for c in result.child_chunks
        ]
        payload: dict[str, Any] = {
            "paper_id": paper_id,
            "question": question,
            "intent": result.intent,
            "passages": passages,
            "metrics": result.metadata,
        }
        if generate:
            payload["answer"] = self._generate(question, result)
        return payload

    def _generate(self, question: str, retrieval) -> str:
        from business.research.rag.retrieval.paper_answer_generator import AnswerGenerator
        from business.research.application.llm_client import build_unity_llm_call

        generator = AnswerGenerator(build_unity_llm_call(max_tokens=600))
        return asyncio.run(generator.generate(question, retrieval)).answer


__all__ = ["PaperRagApplicationService"]
