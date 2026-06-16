from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from framework.llm.clients.openai_compatible import OpenAICompatibleClient, OpenAICompatibleConfig
from framework.llm.models.request import LLMRequest

from infrastructure.document.latex_parser import LatexDocumentParser
from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.storage.postgres.paper_chunk_repository import PaperChunkRepository
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from business.research.document.async_preprocessor import AsyncChunkPreprocessor
from business.research.document.chunker import PaperDocumentChunker


@dataclass
class ChunkPipelineResult:
    paper_id: str
    arxiv_id: str
    total_chunks: int
    by_type: dict[str, int]
    structure_detected: bool
    parse_source: str


def _resolve_api_key_env() -> str:
    """Pick the first configured API-key env var name (OpenAI first, DashScope fallback)."""
    import os
    for env_name in ("OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        if os.environ.get(env_name):
            return env_name
    # default to OPENAI_API_KEY so the error message points users at the standard var
    return "OPENAI_API_KEY"


def _build_default_llm_config() -> OpenAICompatibleConfig:
    import os
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("NEWS_LLM_BASE_URL")
        or os.environ.get("DASHSCOPE_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    model = (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("NEWS_LLM_MODEL")
        or "deepseek-v4-flash"
    )
    return OpenAICompatibleConfig(
        provider="openai-compatible",
        base_url=base_url,
        model=model,
        api_key_env=_resolve_api_key_env(),
    )


def _build_llm_call():
    """Build an async-compatible LLM callable from standard OpenAI env vars."""
    from framework.shared.env import load_root_env
    load_root_env()  # load .env if present, without overriding existing env vars
    client = OpenAICompatibleClient(_build_default_llm_config())

    async def llm_call(prompt: str) -> str:
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        response = await asyncio.to_thread(client.complete, request)
        return response.content or ""

    return llm_call


class ChunkPaperPipeline:
    """
    End-to-end pipeline:
      arXiv ID → download LaTeX source → parse → chunk
                → [optional] LLM proposition decomposition
                → store vectors in Qdrant + metadata in PostgreSQL
    """

    def __init__(
        self,
        chunk_store: PaperChunkStore,
        chunk_repo: PaperChunkRepository,
        *,
        arxiv_connector: ArxivSourceConnector | None = None,
        latex_parser: LatexDocumentParser | None = None,
        chunker: PaperDocumentChunker | None = None,
        with_propositions: bool = True,
    ) -> None:
        self._store = chunk_store
        self._repo = chunk_repo
        self._arxiv = arxiv_connector or ArxivSourceConnector()
        self._parser = latex_parser or LatexDocumentParser()
        self._chunker = chunker or PaperDocumentChunker()
        self._with_propositions = with_propositions

    def run(self, arxiv_id: str) -> ChunkPipelineResult:
        paper_id = arxiv_id.replace("/", "_")

        # 1. download LaTeX source from arXiv
        pkg = self._arxiv.fetch_source_package(arxiv_id)

        # 2. parse LaTeX → ResearchDocument
        doc = self._parser.parse(paper_id, pkg.content)

        # 3. sync chunk (paragraph / section / figure / table / abstract)
        chunks = self._chunker.chunk(doc, "latex")

        # 4. async proposition decomposition + formula descriptions (if LLM available)
        if self._with_propositions:
            try:
                preprocessor = AsyncChunkPreprocessor(_build_llm_call())
                chunks = asyncio.run(preprocessor.preprocess(chunks))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("proposition preprocess skipped: %s", exc)

        # 5a. store in Qdrant (vectors)
        self._store.ensure_collection()
        self._store.index_chunks(chunks)

        # 5b. store in PostgreSQL (metadata + parent-child relationships)
        self._repo.save_chunks(chunks)

        by_type: dict[str, int] = {}
        for c in chunks:
            by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1

        return ChunkPipelineResult(
            paper_id=paper_id,
            arxiv_id=arxiv_id,
            total_chunks=len(chunks),
            by_type=by_type,
            structure_detected=any(c.structure_detected for c in chunks),
            parse_source="latex",
        )


__all__ = ["ChunkPaperPipeline", "ChunkPipelineResult"]
