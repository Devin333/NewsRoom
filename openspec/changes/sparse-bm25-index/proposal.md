## Why

PRD 16 calls out the sparse lexical channel as query-time full scanning over all paper chunks. S1 made the scan production-correct; S9 upgrades it to a paper-scoped BM25 index so sparse recall has an explicit, reusable index path.

## What Changes

- Add a lightweight dependency-free BM25 paper index with JSON persistence.
- Build/update the BM25 index during chunk pipeline ingestion.
- Make `ResearchRetriever` prefer the BM25 index for sparse lexical candidates and fall back to rebuilding from `list_chunks` when the index is missing.
- Preserve existing sparse hit metadata and formula sparse scoring behavior.
- Add tests for BM25 ranking, persistence, ingest wiring, and retriever sparse recall through the index.

## Capabilities

### New Capabilities

- `paper-rag-sparse-bm25-index`: Paper RAG sparse lexical recall uses a paper-scoped BM25 index with observable fallback behavior.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/bm25_index.py`
  - `business/research/application/chunk_paper_pipeline.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval and pipeline tests
- No new external dependency.
