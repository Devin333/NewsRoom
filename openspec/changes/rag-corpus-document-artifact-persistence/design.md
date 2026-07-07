## Context

The chunk manifest path already determines the per-paper artifact directory. Persisting `research_document.json` next to `chunk_manifest.json` and `bm25_index.json` keeps the parsed corpus shape consistent with live eval expectations.

## Decision

Write the parsed document artifact after optional visual description sync and before returning `ChunkPipelineResult`.

This preserves the existing visual path while adding the missing non-visual path. The write is deterministic and uses the existing `_write_research_document_artifact` helper.

## Non-Goals

- Fetch missing historical papers.
- Change chunk identity, BM25 indexing, Qdrant indexing, or Postgres persistence.
- Commit generated `.newsroom/papers` artifacts.
