from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from business.research.document.models import PaperChunk, PropositionQuality

logger = logging.getLogger(__name__)

_PROPOSITION_ROLES: frozenset[str] = frozenset(["related_work", "experiment", "conclusion"])


class AsyncChunkPreprocessor:
    """
    Async preprocessing pipeline: proposition decomposition, formula descriptions.
    Failures degrade gracefully — the chunk is stored as-is, flagged for retry.
    """

    def __init__(
        self,
        llm_call: Callable[[str], Awaitable[str]],
        *,
        proposition_sample_rate: float = 0.1,
    ) -> None:
        self._llm = llm_call
        self._sample_rate = proposition_sample_rate

    async def preprocess(
        self, chunks: list[PaperChunk], *, max_concurrency: int = 2
    ) -> list[PaperChunk]:
        """Returns original chunks (updated) + new proposition chunks."""
        sem = asyncio.Semaphore(max_concurrency)

        async def guarded(c: PaperChunk) -> PaperChunk:
            async with sem:
                return await self._process_chunk(c)

        updated = list(await asyncio.gather(*[guarded(c) for c in chunks]))
        proposition_chunks: list[PaperChunk] = []
        for chunk in updated:
            if chunk.propositions_generated:
                proposition_chunks.extend(self._emit_proposition_chunks(chunk))
        return updated + proposition_chunks

    async def validate_proposition_quality(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        """Sample 10% of proposition-generated chunks and mark quality."""
        eligible = [c for c in chunks if c.propositions_generated]
        if not eligible:
            return chunks

        sample_size = max(1, round(len(eligible) * self._sample_rate))
        sample = random.sample(eligible, sample_size)

        low_ids: set[str] = set()
        for chunk in sample:
            quality = await self._validate_chunk_propositions(chunk)
            if quality == "low":
                low_ids.add(chunk.chunk_id)

        if not low_ids:
            return chunks

        low_ratio = len(low_ids) / len(sample)
        result_quality: PropositionQuality = "low" if low_ratio > 0.3 else "high"
        return [
            chunk.model_copy(update={"proposition_quality": result_quality})
            if chunk.chunk_id in low_ids
            else chunk
            for chunk in chunks
        ]

    def _emit_proposition_chunks(self, chunk: PaperChunk) -> list[PaperChunk]:
        """Create separate PaperChunk objects for each proposition (PRD §5)."""
        from business.foundation import build_stable_id
        propositions: list[str] = chunk.metadata.get("propositions", [])
        result: list[PaperChunk] = []
        for i, text in enumerate(propositions):
            if not text.strip():
                continue
            prop_id = build_stable_id("prop", chunk.chunk_id, str(i))
            result.append(PaperChunk(
                chunk_id=prop_id,
                paper_id=chunk.paper_id,
                parse_source=chunk.parse_source,
                structure_detected=chunk.structure_detected,
                chunk_type="proposition",
                parent_chunk_id=chunk.chunk_id,
                section_title=chunk.section_title,
                section_role=chunk.section_role,
                section_index=chunk.section_index,
                references=chunk.references,
                propositions_generated=True,
                proposition_quality=chunk.proposition_quality,
                content=text,
                metadata={"proposition_index": i, "source_chunk_id": chunk.chunk_id},
            ))
        return result

    async def _process_chunk(self, chunk: PaperChunk) -> PaperChunk:
        updates: dict = {}

        needs_propositions = (
            chunk.metadata.get("needs_proposition_decomposition", False)
            and not chunk.propositions_generated
        )
        if needs_propositions:
            updates.update(await self._decompose_propositions(chunk))

        if chunk.has_formula and chunk.formula_latex and not chunk.formula_description:
            updates.update(await self._describe_formula(chunk))

        return chunk.model_copy(update=updates) if updates else chunk

    async def _decompose_propositions(self, chunk: PaperChunk) -> dict:
        prompt = (
            "Decompose the following text into atomic, self-contained, fluent propositions "
            "(one fact or claim each, no unresolved references). "
            "Return a numbered list, one proposition per line.\n\n"
            f"Text:\n{chunk.content}"
        )
        try:
            raw = await self._llm(prompt)
            propositions = [
                line.lstrip("0123456789. ").strip()
                for line in raw.splitlines()
                if line.strip() and line.lstrip()[:1].isdigit()
            ]
            if not propositions:
                return {"propositions_generated": False}
            return {
                "propositions_generated": True,
                "proposition_quality": "unknown",
                "metadata": {**chunk.metadata, "propositions": propositions},
            }
        except Exception as exc:
            logger.warning("proposition decomposition failed for chunk %s: %s", chunk.chunk_id, exc)
            return {"propositions_generated": False}

    async def _describe_formula(self, chunk: PaperChunk) -> dict:
        prompt = (
            "Write a concise natural language description of the following LaTeX formula, "
            "explaining each symbol based on the context.\n\n"
            f"Formula: {chunk.formula_latex}\n\n"
            f"Context:\n{chunk.content[:600]}"
        )
        try:
            description = (await self._llm(prompt)).strip()
            return {"formula_description": description}
        except Exception:
            logger.warning("formula description failed for chunk %s", chunk.chunk_id)
            return {}

    async def _validate_chunk_propositions(self, chunk: PaperChunk) -> PropositionQuality:
        propositions: list[str] = chunk.metadata.get("propositions", [])
        if not propositions:
            return "unknown"
        prompt = (
            "Can the following proposition be derived from the source text? "
            "Answer only 'yes' or 'no'.\n\n"
            f"Proposition: {propositions[0]}\n\n"
            f"Source: {chunk.content[:800]}"
        )
        try:
            answer = await self._llm(prompt)
            return "high" if "yes" in answer.lower() else "low"
        except Exception:
            return "unknown"


__all__ = ["AsyncChunkPreprocessor"]
