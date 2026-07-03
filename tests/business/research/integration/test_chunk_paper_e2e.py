"""
Integration test: end-to-end chunk pipeline for 1706.03762 (Attention Is All You Need).

Requires explicit opt-in because this is a live integration test:
  NEWS_RUN_LIVE_RESEARCH_E2E=1
  NEWS_QDRANT_URL   (default: http://127.0.0.1:6333)
  NEWS_DATABASE_DSN (e.g.  postgresql://user:pw@localhost/newsroom)

Skip automatically when these are not available.
"""
from __future__ import annotations

import os
import pytest

from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.storage.postgres.migrations import load_migration_sql
from infrastructure.storage.postgres.paper_chunk_repository import PaperChunkRepository
from infrastructure.storage.vector.embeddings import DeterministicEmbeddingModel
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env
from business.research.document.chunk_storage import (
    PaperChunkRepositoryAdapter,
    PaperChunkStoreAdapter,
)
from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline

ARXIV_ID = "1706.03762"
PAPER_ID  = "1706.03762"

_run_live_e2e = os.getenv("NEWS_RUN_LIVE_RESEARCH_E2E", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_has_qdrant = bool(os.getenv("NEWS_QDRANT_URL"))
_has_postgres = bool(os.getenv("NEWS_DATABASE_DSN"))

pytestmark = pytest.mark.skipif(
    not (_run_live_e2e and _has_qdrant and _has_postgres),
    reason=(
        "set NEWS_RUN_LIVE_RESEARCH_E2E=1 with NEWS_QDRANT_URL "
        "and NEWS_DATABASE_DSN to run live chunk paper e2e"
    ),
)


@pytest.fixture(scope="module")
def chunk_store():
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env(
        embedding_model=DeterministicEmbeddingModel(dimension=_vector_size_from_env()),
    )))
    store.ensure_collection()
    return store


@pytest.fixture(scope="module")
def chunk_repo():
    dsn = os.environ["NEWS_DATABASE_DSN"].removeprefix("jdbc:")
    import psycopg
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(load_migration_sql())
        conn.commit()
    return PaperChunkRepositoryAdapter(PaperChunkRepository(dsn))


@pytest.fixture(scope="module")
def pipeline_result(chunk_store, chunk_repo):
    pipeline = ChunkPaperPipeline(
        chunk_store,
        chunk_repo,
        ArxivSourceConnector(),
        ArxivDocumentParser(),
    )
    result = pipeline.run(ARXIV_ID)
    yield result
    # cleanup
    chunk_store.delete_paper_chunks(result.paper_id)
    chunk_repo.delete_paper_chunks(result.paper_id)


def test_pipeline_produces_chunks(pipeline_result):
    assert pipeline_result.total_chunks > 0


def test_pipeline_detects_structure(pipeline_result):
    assert pipeline_result.structure_detected


def test_pipeline_parse_source_is_latex(pipeline_result):
    assert pipeline_result.parse_source == "latex"


def test_pipeline_chunk_types(pipeline_result):
    # expect at least paragraph + abstract
    assert "paragraph" in pipeline_result.by_type or "abstract" in pipeline_result.by_type


def test_chunks_retrievable_from_qdrant(chunk_store, pipeline_result):
    results = chunk_store.search_chunks(
        pipeline_result.paper_id,
        "multi-head attention mechanism",
        limit=5,
    )
    assert results, "expected at least one vector search hit"
    assert all(r.paper_id == pipeline_result.paper_id for r in results)


def test_chunks_retrievable_from_postgres(chunk_repo, pipeline_result):
    rows = chunk_repo.list_paper_chunks(pipeline_result.paper_id)
    assert len(rows) > 0


def test_parent_child_relation_preserved(chunk_repo, pipeline_result):
    rows = chunk_repo.list_paper_chunks(pipeline_result.paper_id)
    payloads = {r["chunk_id"]: r for r in rows}
    children_with_parents = [r for r in rows if r.get("parent_chunk_id")]
    assert children_with_parents, "expected child chunks with parent_chunk_id"
    for child in children_with_parents[:5]:
        assert child["parent_chunk_id"] in payloads, \
            f"parent {child['parent_chunk_id']} not found in postgres"


def test_chunk_summary(pipeline_result):
    print(f"\n=== Chunk summary for {ARXIV_ID} ===")
    print(f"  total     : {pipeline_result.total_chunks}")
    print(f"  by type   : {pipeline_result.by_type}")
    print(f"  structure : {pipeline_result.structure_detected}")


def _vector_size_from_env() -> int:
    return int(os.getenv("NEWS_VECTOR_SIZE") or os.getenv("NEWS_EMBEDDING_DIMENSIONS") or "64")
