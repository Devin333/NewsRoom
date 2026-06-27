from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.paper_retriever import ResearchRetriever, RetrievalRequest
from business.research.ports.chunk_store import ChunkStorePort

logger = logging.getLogger(__name__)

# Only evaluate these chunk types (skip figure/table standalone chunks)
_EVAL_TYPES = frozenset(["paragraph", "proposition", "abstract"])

# Content-level boilerplate guard (catches funding/ack text embedded in prose chunks)
_BOILERPLATE_CONTENT = (
    "acknowledg", "we thank", "this work was supported", "funding", "grant no",
    "conflict of interest", "author contribution",
)

# Meta-question guard: questions about structure/formatting, not content
_META_QUESTION = (
    "which section", "what section", "in which section", "which figure", "what figure",
    "which table", "what table", "exact names", "funding", "acknowledg",
    "following subsection", "v1 to v2", "from v1", "paper's structure",
)


def _is_boilerplate_content(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _BOILERPLATE_CONTENT)


def _is_meta_question(question: str) -> bool:
    low = question.lower()
    return any(kw in low for kw in _META_QUESTION)


@dataclass
class QAPair:
    """A synthetic question whose answer lives in source_chunk_id (ground truth)."""
    question: str
    source_chunk_id: str
    paper_id: str
    domain: str = ""

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "source_chunk_id": self.source_chunk_id,
            "paper_id": self.paper_id,
            "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QAPair":
        return cls(
            question=d["question"],
            source_chunk_id=d["source_chunk_id"],
            paper_id=d["paper_id"],
            domain=d.get("domain", ""),
        )


@dataclass
class EvalResult:
    """Aggregated retrieval metrics over a golden QA set."""
    total: int
    hit_at: dict[int, int] = field(default_factory=dict)     # k -> count of hits in top-k
    reciprocal_ranks: list[float] = field(default_factory=list)  # 1/rank per query (0 if miss)
    ndcg_at: dict[int, list[float]] = field(default_factory=dict)  # k -> per-query ndcg
    by_domain: dict[str, dict[int, int]] = field(default_factory=dict)  # domain -> {k: hits}
    domain_totals: dict[str, int] = field(default_factory=dict)

    def hit_rate(self, k: int) -> float:
        return self.hit_at.get(k, 0) / self.total if self.total else 0.0

    def mrr(self) -> float:
        return sum(self.reciprocal_ranks) / self.total if self.total else 0.0

    def ndcg(self, k: int) -> float:
        scores = self.ndcg_at.get(k, [])
        return sum(scores) / len(scores) if scores else 0.0

    def report(self, ks: tuple[int, ...] = (1, 3, 5, 10)) -> str:
        lines = [f"=== 检索测评 (n={self.total}) ==="]
        for k in ks:
            lines.append(f"  Hit@{k:<2} = {self.hit_rate(k):6.1%}    NDCG@{k:<2} = {self.ndcg(k):.3f}")
        lines.append(f"  MRR     = {self.mrr():.3f}")
        if self.by_domain:
            lines.append("  -- 按领域 Hit@5 --")
            for domain in sorted(self.by_domain):
                total = self.domain_totals.get(domain, 0)
                hit5 = self.by_domain[domain].get(5, 0)
                rate = hit5 / total if total else 0.0
                lines.append(f"     {domain:<18} {rate:6.1%}  (n={total})")
        return "\n".join(lines)


class GoldenSetBuilder:
    """阶段A：LLM 合成问答对 → 固化到磁盘（跑一次，人工抽检后复用）。"""

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        llm_call,                          # Callable[[str], Awaitable[str]]
        *,
        questions_per_chunk: int = 2,
        max_chunks_per_paper: int = 30,
        max_concurrency: int = 3,
    ) -> None:
        self._store = chunk_store
        self._llm = llm_call
        self._q_per_chunk = questions_per_chunk
        self._max_chunks = max_chunks_per_paper
        self._sem = asyncio.Semaphore(max_concurrency)

    async def build(self, paper_ids: dict[str, str]) -> list[QAPair]:
        """paper_ids: {paper_id: domain}. 对每篇取样章节，生成问答对。"""
        all_pairs: list[QAPair] = []
        for paper_id, domain in paper_ids.items():
            pairs = await self._build_for_paper(paper_id, domain)
            logger.info("paper %s (%s): %d QA pairs", paper_id, domain, len(pairs))
            all_pairs.extend(pairs)
        return all_pairs

    async def _build_for_paper(self, paper_id: str, domain: str) -> list[QAPair]:
        chunks = self._store.search_chunks(
            paper_id, "method experiment result conclusion background",
            limit=self._max_chunks,
        )
        eligible = [
            c for c in chunks
            if c.chunk_type in _EVAL_TYPES
            and len(c.content) > 120                 # skip stubs
            and not _is_boilerplate_content(c.content)
        ]
        tasks = [self._questions_for_chunk(c) for c in eligible]
        results = await asyncio.gather(*tasks)
        pairs: list[QAPair] = []
        for chunk, questions in zip(eligible, results):
            for q in questions:
                if _is_meta_question(q):
                    continue                          # drop section/figure-location/structure questions
                pairs.append(QAPair(question=q, source_chunk_id=chunk.chunk_id,
                                    paper_id=paper_id, domain=domain))
        return pairs

    async def _questions_for_chunk(self, chunk: PaperChunk) -> list[str]:
        prompt = (
            f"You are building a retrieval test set. Based ONLY on the text below, write exactly "
            f"{self._q_per_chunk} specific, self-contained questions whose answer is stated in the text.\n"
            "Rules:\n"
            "- Ask about the research content (methods, results, definitions, claims).\n"
            "- Do NOT ask about the paper's structure (e.g. 'which section', 'what figure shows').\n"
            "- Do NOT ask about acknowledgments, funding, authors, or formatting.\n"
            "- Each question must stand alone (no 'V1/V2', 'the above', unresolved references).\n"
            "Return only the questions, one per line, no numbering.\n\n"
            f"Text:\n{chunk.content[:700]}"
        )
        async with self._sem:
            try:
                raw = await self._llm(prompt)
            except Exception as exc:
                logger.warning("QA generation failed for %s: %s", chunk.chunk_id, exc)
                return []
        return [q.strip().lstrip("0123456789.-) ").strip()
                for q in raw.splitlines() if q.strip()][:self._q_per_chunk]


def save_golden_set(pairs: list[QAPair], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([qa.to_dict() for qa in pairs], ensure_ascii=False, indent=2),
                 encoding="utf-8")


def load_golden_set(path: str | Path) -> list[QAPair]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [QAPair.from_dict(d) for d in data]


class RetrievalEvaluator:
    """阶段B：加载黄金集 → 跑检索 → 出 Hit@K / MRR / NDCG（可反复跑/CI）。"""

    def __init__(self, retriever: ResearchRetriever) -> None:
        self._retriever = retriever

    def evaluate(self, pairs: list[QAPair], ks: tuple[int, ...] = (1, 3, 5, 10)) -> EvalResult:
        max_k = max(ks)
        result = EvalResult(total=len(pairs), hit_at={k: 0 for k in ks},
                            ndcg_at={k: [] for k in ks})
        for pair in pairs:
            retrieved = self._retriever.retrieve(RetrievalRequest(
                paper_id=pair.paper_id, question=pair.question, limit=max_k,
            )).child_chunks
            ranked_ids = [c.chunk_id for c in retrieved]
            rank = ranked_ids.index(pair.source_chunk_id) + 1 if pair.source_chunk_id in ranked_ids else 0

            result.reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            dom = result.by_domain.setdefault(pair.domain, {k: 0 for k in ks})
            result.domain_totals[pair.domain] = result.domain_totals.get(pair.domain, 0) + 1
            for k in ks:
                hit = bool(rank and rank <= k)
                if hit:
                    result.hit_at[k] += 1
                    dom[k] += 1
                # binary-relevance NDCG: ideal DCG = 1, so NDCG = 1/log2(rank+1) if within k else 0
                result.ndcg_at[k].append(1.0 / math.log2(rank + 1) if hit else 0.0)
        return result


__all__ = [
    "EvalResult", "GoldenSetBuilder", "QAPair", "RetrievalEvaluator",
    "load_golden_set", "save_golden_set",
]
