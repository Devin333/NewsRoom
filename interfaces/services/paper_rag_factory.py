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
from infrastructure.storage.vector.paper_field_chunk_store import PaperFieldChunkStore
from infrastructure.storage.vector.paper_visual_chunk_store import (
    PaperVisualChunkStore,
    paper_visual_chunk_store_from_env,
)
from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env

from business.research.document.chunk_storage import (
    PaperChunkRepositoryAdapter,
    PaperChunkStoreAdapter,
)
from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline
from business.research.application.visual_chunk_describer import build_visual_chunk_describer_from_env
from business.research.application.paper_rag_session import PaperRAGSession
from business.research.rag.retrieval.paper_retriever import (
    ResearchRetriever,
    build_retrieval_policy_from_env,
)


def _dsn() -> str:
    from infrastructure.storage.postgres.dsn import normalize_dsn
    dsn = os.environ.get("NEWS_DATABASE_DSN", "")
    if not dsn:
        raise RuntimeError("NEWS_DATABASE_DSN is not set")
    return normalize_dsn(dsn)


# Process-wide singleton: loading the cross-encoder weights costs ~18s, so the
# reranker is built once and reused across requests (kept resident in memory).
_RERANKER_SINGLETON: CrossEncoderReranker | None = None


def get_reranker() -> CrossEncoderReranker:
    global _RERANKER_SINGLETON
    if _RERANKER_SINGLETON is None:
        _RERANKER_SINGLETON = CrossEncoderReranker()
    return _RERANKER_SINGLETON


def preload_reranker() -> None:
    """Warm the reranker weights at service startup so the first request is fast."""
    get_reranker().score("warmup", ["warmup passage"])


def build_chunk_store() -> PaperChunkStoreAdapter:
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    store.ensure_collection()
    return store


def build_chunk_repository() -> PaperChunkRepositoryAdapter:
    return PaperChunkRepositoryAdapter(PaperChunkRepository(_dsn()))


def build_field_chunk_store() -> PaperFieldChunkStore:
    store = PaperFieldChunkStore(qdrant_store_from_env())
    store.ensure_collection()
    return store


def build_visual_chunk_store() -> PaperVisualChunkStore | None:
    store = paper_visual_chunk_store_from_env()
    if store is not None:
        store.ensure_collection()
    return store


def build_chunk_pipeline(*, with_propositions: bool = False) -> ChunkPaperPipeline:
    return ChunkPaperPipeline(
        build_chunk_store(),
        build_chunk_repository(),
        ArxivSourceConnector(),
        ArxivDocumentParser(),
        field_chunk_indexer=build_field_chunk_store(),
        visual_chunk_indexer=build_visual_chunk_store(),
        visual_chunk_describer=build_visual_chunk_describer_from_env(),
        with_propositions=with_propositions,
    )


def build_research_retriever(*, with_reranker: bool = True) -> ResearchRetriever:
    reranker = get_reranker() if with_reranker else None
    retrieval_policy = build_retrieval_policy_from_env()
    return ResearchRetriever(
        build_chunk_store(),
        policy=retrieval_policy,
        reranker=reranker,
        field_index=build_field_chunk_store(),
        field_reranker=reranker,
        visual_store=build_visual_chunk_store(),
    )


def build_paper_rag_session(*, with_reranker: bool = True) -> PaperRAGSession:
    reranker = get_reranker() if with_reranker else None
    retrieval_policy = build_retrieval_policy_from_env()
    return PaperRAGSession(
        build_chunk_store(),
        reranker=reranker,
        field_index=build_field_chunk_store(),
        field_reranker=reranker,
        visual_store=build_visual_chunk_store(),
        retrieval_policy=retrieval_policy,
    )


__all__ = [
    "build_chunk_pipeline",
    "build_chunk_repository",
    "build_chunk_store",
    "build_field_chunk_store",
    "build_visual_chunk_store",
    "build_paper_rag_session",
    "build_research_retriever",
    "get_reranker",
    "preload_reranker",
]
