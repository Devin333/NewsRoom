from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from framework.llm.clients.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)
from framework.llm.models.request import LLMRequest
from framework.shared.env import load_root_env

from business.research.document.async_preprocessor import AsyncChunkPreprocessor
from business.research.document.chunk_manifest import ChunkManifestManager
from business.research.document.chunker import PaperDocumentChunker
from business.research.document.visual_document_sync import sync_visual_descriptions_to_document
from business.research.ports.chunk_indexer import ChunkIndexerPort
from business.research.ports.chunk_repository import ChunkRepositoryPort
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.document_parser import DocumentParserPort
from business.research.ports.field_embedding_index import FieldEmbeddingIndexerPort
from business.research.ports.source_fetcher import SourceFetcherPort
from business.research.ports.visual_description import VisualChunkDescriptionPort
from business.research.ports.visual_chunk_index import VisualChunkIndexerPort


@dataclass
class ChunkPipelineResult:
    paper_id: str
    arxiv_id: str
    total_chunks: int
    by_type: dict[str, int]
    structure_detected: bool
    parse_source: str
    chunk_manifest_path: str = ""
    visual_described_chunks: int = 0


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
        visual_chunk_indexer: VisualChunkIndexerPort | None = None,
        field_chunk_indexer: FieldEmbeddingIndexerPort | None = None,
        visual_chunk_describer: VisualChunkDescriptionPort | None = None,
        chunker: PaperDocumentChunker | None = None,
        chunk_manifest: ChunkManifestManager | None = None,
        with_propositions: bool = True,
    ) -> None:
        self._store = chunk_store
        self._repo = chunk_repo
        self._fetcher = source_fetcher
        self._parser = document_parser
        self._indexer = chunk_indexer or chunk_store  # PaperChunkStore satisfies both
        self._visual_indexer = visual_chunk_indexer
        self._field_indexer = field_chunk_indexer
        self._visual_describer = visual_chunk_describer
        self._chunker = chunker or PaperDocumentChunker()
        self._chunk_manifest = chunk_manifest or ChunkManifestManager()
        self._with_propositions = with_propositions

    def run(self, arxiv_id: str) -> ChunkPipelineResult:
        import logging
        paper_id = arxiv_id.replace("/", "_")

        pkg = self._fetcher.fetch_source_package(arxiv_id)
        doc = self._parser.parse(paper_id, pkg.content)
        parse_source = doc.metadata.get("parse_source", "latex")
        chunks = self._chunker.chunk(doc, parse_source)
        chunks = self._chunk_manifest.resolve_chunk_ids(paper_id, chunks)

        if self._with_propositions:
            try:
                preprocessor = AsyncChunkPreprocessor(_build_llm_call())
                chunks = asyncio.run(preprocessor.preprocess(chunks))
            except Exception as exc:
                logging.getLogger(__name__).warning("proposition preprocess skipped: %s", exc)

        chunks = self._chunk_manifest.resolve_chunk_ids(paper_id, chunks)
        visual_described_chunks = 0
        if self._visual_describer is not None:
            before = {
                chunk.chunk_id: str(chunk.metadata.get("visual_description") or "")
                for chunk in chunks
            }
            chunks = self._visual_describer.describe_chunks(chunks)
            doc = sync_visual_descriptions_to_document(doc, chunks)
            visual_described_chunks = sum(
                1
                for chunk in chunks
                if str(chunk.metadata.get("visual_description") or "")
                and str(chunk.metadata.get("visual_description") or "") != before.get(chunk.chunk_id, "")
            )
            _write_research_document_artifact(
                doc,
                self._chunk_manifest.path_for(paper_id).with_name("research_document.json"),
            )
        self._store.ensure_collection()
        self._indexer.index_chunks(chunks)
        if self._field_indexer is not None:
            self._field_indexer.ensure_collection()
            self._field_indexer.index_chunks(chunks)
        if self._visual_indexer is not None:
            self._visual_indexer.ensure_collection()
            self._visual_indexer.index_chunks(chunks)
        self._repo.save_chunks(chunks)
        manifest_path = self._chunk_manifest.write(paper_id, chunks)

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
            chunk_manifest_path=str(manifest_path),
            visual_described_chunks=visual_described_chunks,
        )


__all__ = ["ChunkPaperPipeline", "ChunkPipelineResult"]


def _write_research_document_artifact(doc, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(doc.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
