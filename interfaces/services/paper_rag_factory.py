"""Composition root for the paper RAG stack.

Wires the four storage/parsing ports + reranker into ready-to-use pipeline,
retriever and session objects so callers (CLI, services, scripts) never repeat
the adapter assembly.

This module lives in interfaces/ because it is the only layer allowed to import
both business and infrastructure (the architecture boundary forbids business → infra).
"""
from __future__ import annotations

import os

from infrastructure.external.reranker import CrossEncoderReranker
from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.storage.postgres.paper_chunk_repository import PaperChunkRepository
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env

from business.research.document.chunk_storage import (
    PaperChunkRepositoryAdapter,
    PaperChunkStoreAdapter,
)
from business.research.document.latex_compiler import LatexSourceParser
from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline
from business.research.application.paper_rag_session import PaperRAGSession
from business.research.rag.retriever import ResearchRetriever


def _dsn() -> str:
    dsn = os.environ.get("NEWS_DATABASE_DSN", "")
    if not dsn:
        raise RuntimeError("NEWS_DATABASE_DSN is not set")
    return dsn.removeprefix("jdbc:")


def build_chunk_store() -> PaperChunkStoreAdapter:
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    store.ensure_collection()
    return store


def build_chunk_repository() -> PaperChunkRepositoryAdapter:
    return PaperChunkRepositoryAdapter(PaperChunkRepository(_dsn()))


def build_chunk_pipeline(*, with_propositions: bool = False) -> ChunkPaperPipeline:
    return ChunkPaperPipeline(
        build_chunk_store(),
        build_chunk_repository(),
        ArxivSourceConnector(),
        LatexSourceParser(),
        with_propositions=with_propositions,
    )


def build_research_retriever(*, with_reranker: bool = True) -> ResearchRetriever:
    reranker = CrossEncoderReranker() if with_reranker else None
    return ResearchRetriever(build_chunk_store(), reranker=reranker)


def build_paper_rag_session(*, with_reranker: bool = True) -> PaperRAGSession:
    reranker = CrossEncoderReranker() if with_reranker else None
    return PaperRAGSession(build_chunk_store(), reranker=reranker)


__all__ = [
    "build_chunk_pipeline",
    "build_chunk_repository",
    "build_chunk_store",
    "build_paper_rag_session",
    "build_research_retriever",
]
