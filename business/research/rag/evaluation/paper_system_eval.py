from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

LLMCall = Callable[[str], Awaitable[str]]


@dataclass
class SystemSample:
    """One end-to-end evaluation sample."""
    question: str
    generated_answer: str
    ground_truth: str          # text of the source chunk the question was derived from
    retrieval_hit: bool        # did retrieval surface the source chunk in top-k?
    correctness: float = 0.0   # judge: is the answer correct vs ground truth (0~1)


@dataclass
class SystemEvalResult:
    per_sample: list[SystemSample] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.per_sample)

    def answer_correctness(self) -> float:
        if not self.per_sample:
            return 0.0
        return sum(s.correctness for s in self.per_sample) / self.total

    def retrieval_hit_rate(self) -> float:
        if not self.per_sample:
            return 0.0
        return sum(1 for s in self.per_sample if s.retrieval_hit) / self.total

    def end_to_end_success(self, threshold: float = 0.7) -> float:
        """检索命中 且 答案正确(correctness≥threshold) 的比例。"""
        if not self.per_sample:
            return 0.0
        return sum(
            1 for s in self.per_sample if s.retrieval_hit and s.correctness >= threshold
        ) / self.total

    def report(self) -> str:
        return (
            f"=== 整体系统测评 (n={self.total}) ===\n"
            f"  Answer Correctness   = {self.answer_correctness():.3f}\n"
            f"  Retrieval Hit Rate   = {self.retrieval_hit_rate():.1%}\n"
            f"  End-to-End Success   = {self.end_to_end_success():.1%}  (命中+正确)"
        )


def _extract_float(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return default
    val = float(m.group(1))
    return max(0.0, min(1.0, val / 100.0 if val > 1.0 else val))


class SystemEvaluator:
    """端到端整体系统测评：Answer Correctness (vs ground truth) + 检索命中 + 端到端成功率。"""

    def __init__(self, judge_llm: LLMCall, *, max_concurrency: int = 3) -> None:
        self._llm = judge_llm
        self._sem = asyncio.Semaphore(max_concurrency)

    async def evaluate(self, samples: list[SystemSample]) -> SystemEvalResult:
        scored = await asyncio.gather(*[self._score_one(s) for s in samples])
        return SystemEvalResult(per_sample=list(scored))

    async def _score_one(self, sample: SystemSample) -> SystemSample:
        async with self._sem:
            sample.correctness = await self._answer_correctness(sample)
        return sample

    async def _answer_correctness(self, sample: SystemSample) -> float:
        if not sample.generated_answer.strip():
            return 0.0
        prompt = (
            "Judge whether the ANSWER is factually correct and complete with respect to the "
            "REFERENCE (the ground-truth source text). Score 0 to 100:\n"
            "- 100 = fully correct and complete\n"
            "- 50  = partially correct or incomplete\n"
            "- 0   = wrong or unsupported\n"
            "Reply with only the number.\n\n"
            f"QUESTION: {sample.question}\n\n"
            f"REFERENCE:\n{sample.ground_truth[:2000]}\n\n"
            f"ANSWER:\n{sample.generated_answer}\n\n"
            "Score (0-100):"
        )
        try:
            return _extract_float(await self._llm(prompt))
        except Exception as exc:
            logger.warning("correctness judge failed: %s", exc)
            return 0.0


__all__ = ["SystemEvaluator", "SystemEvalResult", "SystemSample"]
