from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infrastructure.document.latex_parser import LatexDocumentParser
from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.storage.postgres.paper_chunk_repository import PaperChunkRepository
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from business.research.document.chunker import PaperDocumentChunker
from business.research.document.models import PaperChunk


@dataclass
class ChunkPipelineResult:
    paper_id: str
    arxiv_id: str
    total_chunks: int
    by_type: dict[str, int]
    structure_detected: bool
    parse_source: str


class ChunkPaperPipeline:
    """
    End-to-end pipeline:
      arXiv ID → download LaTeX source → parse → chunk
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
    ) -> None:
        self._store = chunk_store
        self._repo = chunk_repo
        self._arxiv = arxiv_connector or ArxivSourceConnector()
        self._parser = latex_parser or LatexDocumentParser()
        self._chunker = chunker or PaperDocumentChunker()

    def run(self, arxiv_id: str) -> ChunkPipelineResult:
        paper_id = arxiv_id.replace("/", "_")

        # 1. download LaTeX source from arXiv
        pkg = self._arxiv.fetch_source_package(arxiv_id)

        # 2. parse LaTeX → ResearchDocument
        doc = self._parser.parse(paper_id, pkg.content)

        # 3. chunk
        chunks = self._chunker.chunk(doc, "latex")

        # 4a. store in Qdrant (vectors)
        self._store.ensure_collection()
        self._store.index_chunks(chunks)

        # 4b. store in PostgreSQL (metadata + relationships)
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
