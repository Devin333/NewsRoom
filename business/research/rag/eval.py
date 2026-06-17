from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from business.research.document.models import PaperChunk
from business.research.rag.retriever import ResearchRetriever, RetrievalRequest
from business.research.ports.chunk_store import ChunkStorePort

logger = logging.getLogger(__name__)

# Only evaluate these chunk types (skip figure/table standalone chunks)
_EVAL_TYPES = frozenset(["paragraph", "proposition", "abstract"])


@dataclass
class QAPair:
    question: str
    source_chunk_id: str
    paper_id: str


@dataclass
class EvalResult:
    paper_id: str
    total: int
    hit_at: dict[int, int] = field(default_factory=dict)   # k -> count

    def hit_rate(self, k: int) -> float:
        return self.hit_at.get(k, 0) / self.total if self.total else 0.0

    def report(self, ks: tuple[int, ...] = (1, 3, 5)) -> str:
        lines = [f"paper={self.paper_id}  n={self.total}"]
        for k in ks:
            lines.append(f"  Hit@{k} = {self.hit_rate(k):.1%}")
        return "\n".join(lines)


class RecallEvaluator:
    """
    1. generate_qa_pairs: for each eligible chunk, ask LLM to generate N questions
    2. evaluate: run retriever on each question, check if source chunk appears in child_chunks
    """

    def __init__(
        self,
        retriever: ResearchRetriever,
        chunk_store: ChunkStorePort,
        llm_call,                       # Callable[[str], Awaitable[str]]
        *,
        questions_per_chunk: int = 2,
        max_chunks: int = 50,           # cap to control LLM cost
    ) -> None:
        self._retriever = retriever
        self._store = chunk_store
        self._llm = llm_call
        self._q_per_chunk = questions_per_chunk
        self._max_chunks = max_chunks

    # ── public ───────────────────────────────────────────────────────────────

    async def generate_qa_pairs(self, paper_id: str) -> list[QAPair]:
        chunks = self._store.search_chunks(
            paper_id, "method experiment result conclusion",
            limit=self._max_chunks,
        )
        eligible = [c for c in chunks if c.chunk_type in _EVAL_TYPES and len(c.content) > 80][:self._max_chunks]
        logger.info("generating QA pairs from %d chunks", len(eligible))
        tasks = [self._questions_for_chunk(c) for c in eligible]
        results = await asyncio.gather(*tasks)
        pairs: list[QAPair] = []
        for chunk, questions in zip(eligible, results):
            for q in questions:
                pairs.append(QAPair(question=q, source_chunk_id=chunk.chunk_id, paper_id=paper_id))
        return pairs

    def evaluate(self, pairs: list[QAPair], ks: tuple[int, ...] = (1, 3, 5)) -> EvalResult:
        paper_id = pairs[0].paper_id if pairs else ""
        hit_at = {k: 0 for k in ks}
        for pair in pairs:
            result = self._retriever.retrieve(RetrievalRequest(
                paper_id=pair.paper_id,
                question=pair.question,
                limit=max(ks),
            ))
            retrieved_ids = {c.chunk_id for c in result.child_chunks}
            for k in ks:
                top_k_ids = {c.chunk_id for c in result.child_chunks[:k]}
                if pair.source_chunk_id in top_k_ids:
                    hit_at[k] += 1
        return EvalResult(paper_id=paper_id, total=len(pairs), hit_at=hit_at)

    # ── private ───────────────────────────────────────────────────────────────

    async def _questions_for_chunk(self, chunk: PaperChunk) -> list[str]:
        prompt = (
            f"Based on the following text, write exactly {self._q_per_chunk} distinct questions "
            "that a reader might ask whose answer is contained in this text. "
            "Return only the questions, one per line, no numbering.\n\n"
            f"Text:\n{chunk.content[:600]}"
        )
        try:
            raw = await self._llm(prompt)
            return [q.strip() for q in raw.splitlines() if q.strip()][:self._q_per_chunk]
        except Exception as exc:
            logger.warning("QA generation failed for %s: %s", chunk.chunk_id, exc)
            return []


__all__ = ["EvalResult", "QAPair", "RecallEvaluator"]
