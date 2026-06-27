from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from business.research.rag.retrieval.paper_answer_generator import GeneratedAnswer

logger = logging.getLogger(__name__)

LLMCall = Callable[[str], Awaitable[str]]


@dataclass
class GenerationScores:
    faithfulness: float          # 答案论断有多少能从 context 推出 (0~1)
    answer_relevancy: float      # 答案与问题的相关度 (0~1)
    context_precision: float     # 检索 context 中真正相关的比例 (0~1)

    def to_dict(self) -> dict:
        return {
            "faithfulness": round(self.faithfulness, 3),
            "answer_relevancy": round(self.answer_relevancy, 3),
            "context_precision": round(self.context_precision, 3),
        }


@dataclass
class GenerationEvalResult:
    per_sample: list[GenerationScores] = field(default_factory=list)

    def _avg(self, attr: str) -> float:
        vals = [getattr(s, attr) for s in self.per_sample]
        return sum(vals) / len(vals) if vals else 0.0

    def faithfulness_score(self) -> float:
        return self._avg("faithfulness")

    def answer_relevancy_score(self) -> float:
        return self._avg("answer_relevancy")

    def context_precision_score(self) -> float:
        return self._avg("context_precision")

    def report(self) -> str:
        n = len(self.per_sample)
        return (
            f"=== 生成测评 (n={n}) ===\n"
            f"  Faithfulness      = {self.faithfulness_score():.3f}\n"
            f"  Answer Relevancy  = {self.answer_relevancy_score():.3f}\n"
            f"  Context Precision = {self.context_precision_score():.3f}"
        )


def _extract_float(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return default
    val = float(m.group(1))
    return max(0.0, min(1.0, val / 100.0 if val > 1.0 else val))


def _parse_yes_ratio(text: str) -> float:
    """Count yes/no tokens in a verdict list, return yes-ratio."""
    tokens = re.findall(r"\b(yes|no)\b", text.lower())
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t == "yes") / len(tokens)


class GenerationEvaluator:
    """LLM-as-judge 生成测评：Faithfulness / Answer Relevancy / Context Precision。"""

    def __init__(self, judge_llm: LLMCall, *, max_concurrency: int = 3) -> None:
        self._llm = judge_llm
        self._sem = asyncio.Semaphore(max_concurrency)

    async def evaluate(self, answers: list[GeneratedAnswer]) -> GenerationEvalResult:
        scores = await asyncio.gather(*[self._score_one(a) for a in answers])
        return GenerationEvalResult(per_sample=list(scores))

    async def _score_one(self, ans: GeneratedAnswer) -> GenerationScores:
        async with self._sem:
            faith = await self._faithfulness(ans)
            relevancy = await self._answer_relevancy(ans)
            precision = await self._context_precision(ans)
        return GenerationScores(faith, relevancy, precision)

    # ── Faithfulness: 答案的每条论断能否从 context 推出 ──────────────────────────
    async def _faithfulness(self, ans: GeneratedAnswer) -> float:
        context = "\n\n".join(ans.contexts)
        prompt = (
            "Break the ANSWER into individual factual claims. For each claim, judge whether "
            "it can be inferred from the CONTEXT. Reply one line per claim as 'yes' or 'no'.\n\n"
            f"CONTEXT:\n{context[:4000]}\n\n"
            f"ANSWER:\n{ans.answer}\n\n"
            "Verdicts (yes/no per claim):"
        )
        try:
            return _parse_yes_ratio(await self._llm(prompt))
        except Exception as exc:
            logger.warning("faithfulness judge failed: %s", exc)
            return 0.0

    # ── Answer Relevancy: 答案是否切题 ──────────────────────────────────────────
    async def _answer_relevancy(self, ans: GeneratedAnswer) -> float:
        prompt = (
            "On a scale of 0 to 100, how directly and completely does the ANSWER address the "
            "QUESTION? Reply with only the number.\n\n"
            f"QUESTION: {ans.question}\n\n"
            f"ANSWER: {ans.answer}\n\n"
            "Score (0-100):"
        )
        try:
            return _extract_float(await self._llm(prompt))
        except Exception as exc:
            logger.warning("relevancy judge failed: %s", exc)
            return 0.0

    # ── Context Precision: 检索到的 context 有多少真正相关 ──────────────────────
    async def _context_precision(self, ans: GeneratedAnswer) -> float:
        if not ans.contexts:
            return 0.0
        prompt = (
            "For each numbered passage, judge whether it is relevant for answering the QUESTION. "
            "Reply one line per passage as 'yes' or 'no'.\n\n"
            f"QUESTION: {ans.question}\n\n"
            + "\n\n".join(f"[{i+1}] {c[:600]}" for i, c in enumerate(ans.contexts))
            + "\n\nVerdicts (yes/no per passage):"
        )
        try:
            return _parse_yes_ratio(await self._llm(prompt))
        except Exception as exc:
            logger.warning("context precision judge failed: %s", exc)
            return 0.0


__all__ = [
    "GenerationEvaluator", "GenerationEvalResult", "GenerationScores",
]
