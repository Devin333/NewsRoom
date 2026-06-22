from __future__ import annotations

import asyncio
from dataclasses import dataclass

from framework.llm.clients.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)
from framework.llm.models.request import LLMRequest
from framework.shared.env import load_root_env

from business.research.document.async_preprocessor import AsyncChunkPreprocessor
from business.research.document.chunker import PaperDocumentChunker
from business.research.ports.chunk_indexer import ChunkIndexerPort
from business.research.ports.chunk_repository import ChunkRepositoryPort
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.document_parser import DocumentParserPort
from business.research.ports.source_fetcher import SourceFetcherPort


@dataclass
class ChunkPipelineResult:
    paper_id: str
    arxiv_id: str
    total_chunks: int
    by_type: dict[str, int]
    structure_detected: bool
    parse_source: str


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _browser_transport(request, timeout_seconds: float) -> bytes:
    """Wrap urllib transport with a browser User-Agent (needed for Cloudflare-proxied APIs)."""
    import urllib.request
    request.add_header("User-Agent", _BROWSER_UA)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as r:
        return r.read()


def _build_llm_call():
    """Async LLM callable using OPENAI_* env vars (unity2.ai / gpt-5.4-mini)."""
    load_root_env()
    import os
    config = OpenAICompatibleConfig(
        provider="openai-compatible",
        base_url=os.environ["OPENAI_BASE_URL"].rstrip("/"),
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        api_key_env="OPENAI_API_KEY",
    )
    client = OpenAICompatibleClient(config, transport=_browser_transport)

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
                → [optional] LLM proposition decomposition + formula descriptions
                → store vectors in Qdrant + metadata in PostgreSQL
    """

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        chunk_repo: ChunkRepositoryPort,
        source_fetcher: SourceFetcherPort,
        document_parser: DocumentParserPort,
        *,
        chunk_indexer: ChunkIndexerPort | None = None,
        chunker: PaperDocumentChunker | None = None,
        with_propositions: bool = True,
    ) -> None:
        self._store = chunk_store
        self._repo = chunk_repo
        self._fetcher = source_fetcher
        self._parser = document_parser
        self._indexer = chunk_indexer or chunk_store  # PaperChunkStore satisfies both
        self._chunker = chunker or PaperDocumentChunker()
        self._with_propositions = with_propositions

    def run(self, arxiv_id: str) -> ChunkPipelineResult:
        import logging
        paper_id = arxiv_id.replace("/", "_")

        pkg = self._fetcher.fetch_source_package(arxiv_id)
        doc = self._parser.parse(paper_id, pkg.content)
        parse_source = doc.metadata.get("parse_source", "latex")
        chunks = self._chunker.chunk(doc, parse_source)

        if self._with_propositions:
            try:
                preprocessor = AsyncChunkPreprocessor(_build_llm_call())
                chunks = asyncio.run(preprocessor.preprocess(chunks))
            except Exception as exc:
                logging.getLogger(__name__).warning("proposition preprocess skipped: %s", exc)

        self._store.ensure_collection()
        self._indexer.index_chunks(chunks)
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
            parse_source=parse_source,
        )


__all__ = ["ChunkPaperPipeline", "ChunkPipelineResult"]
