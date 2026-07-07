## Why

PRD 16 targets homogeneous recall channels and removal of source-specific adapter logic from `paper_retriever.py`. Dense, sparse, and claim recall are already channels. Field embedding recall still performs search, hit deduplication, metadata merge, and RRF ranking conversion inline in the retriever.

## What Changes

- Add `FieldEmbeddingChannel` under `business.research.rag.retrieval.channels`.
- Move field vector search, `(chunk_id, field_name)` deduplication, field metadata merge, and field ranking conversion into the channel.
- Delegate field search, candidate merge, and hybrid RRF field ranking from `ResearchRetriever`.
- Add focused channel tests.

## Capabilities

### New Capabilities

- `paper-rag-field-embedding-channel`: Field embedding recall is implemented as a reusable recall channel.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/field_embedding.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval channel tests
- No intended behavior change to field scores, metadata, or hybrid RRF ordering.
