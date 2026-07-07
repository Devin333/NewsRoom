## Why

Paper RAG's hybrid retrieval policy depends on a sparse lexical channel, but the current retriever discovers `list_chunks` by reflection and silently returns an empty list when the production chunk store does not expose it. This makes offline evaluation and production wiring diverge: in-memory tests can exercise sparse recall while the production `PaperChunkStoreAdapter` can degrade to dense-only retrieval without an explicit signal.

## What Changes

- Add an explicit `ChunkStorePort.list_chunks(paper_id: str) -> list[PaperChunk]` contract.
- Implement `PaperChunkStoreAdapter.list_chunks` over the storage-facing payload store.
- Extend the storage-facing `ChunkPayloadStorePort` and Qdrant-backed `PaperChunkStore` with paper-scoped payload listing.
- Remove reflection-based `_list_store_chunks` fallback from `ResearchRetriever`.
- Record sparse-channel degradation metadata when sparse recall is enabled but no chunk inventory is available.
- Add tests proving production-style adapters expose paper chunks and sparse recall remains active without private attribute reflection.

## Capabilities

### New Capabilities
- `paper-rag-sparse-production-wiring`: Paper RAG sparse lexical retrieval is backed by an explicit chunk listing contract and remains observable in production-style adapter wiring.

### Modified Capabilities
- None.

## Impact

- Affected code:
  - `business/research/ports/chunk_store.py`
  - `business/research/ports/chunk_payload_store.py`
  - `business/research/document/chunk_storage.py`
  - `infrastructure/storage/vector/paper_chunk_store.py`
  - `infrastructure/storage/vector/qdrant_store.py`
  - `infrastructure/storage/vector/fake_store.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - Paper RAG retrieval and vector storage tests
- No external API contract changes for answer generation or `RetrievalResult`.
- No new external dependency.
