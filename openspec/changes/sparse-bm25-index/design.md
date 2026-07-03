## Context

The sparse lexical path currently calls `ChunkStorePort.list_chunks(paper_id)` and scores each chunk with token overlap. This is correct after S1, but it still makes query latency scale with all chunks and leaves no reusable lexical index artifact.

## Goals / Non-Goals

**Goals:**

- Build a paper-scoped BM25 index from `PaperChunk` content and selected metadata fields.
- Persist the index beside paper artifacts for reuse across retrieval calls.
- Preserve existing sparse candidate metadata and formulas-specific sparse boosts.
- Keep a safe rebuild fallback when no persisted index exists.

**Non-Goals:**

- Do not add a new search server.
- Do not remove `list_chunks` fallback.
- Do not replace formula symbol scoring; combine BM25 with the existing formula sparse logic.

## Decisions

- **Dependency-free BM25:** Implement BM25 directly to avoid adding `rank_bm25` and changing runtime packaging.
- **Paper artifact storage:** Store `.newsroom/papers/<paper_id>/bm25_index.json` using the existing `NEWS_ARTIFACT_ROOT` convention.
- **Retriever-side lazy rebuild:** If the persisted index is missing, the retriever can build an in-memory index from `list_chunks`, record a degradation, and continue.

## Risks / Trade-offs

- **Index can be stale** -> Ingest rewrites the paper index after chunking; metadata includes a chunk count and index version.
- **Large paper index JSON** -> Per-paper chunk counts are modest, and the index stores terms/doc stats only.
