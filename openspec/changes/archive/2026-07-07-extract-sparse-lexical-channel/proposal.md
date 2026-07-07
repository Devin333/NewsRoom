## Why

PRD 16 targets homogeneous recall channels and a thinner `paper_retriever.py`. The sparse lexical path now has production BM25 wiring, but the candidate loading, fallback trace, lexical scoring, and formula sparse fallback still live inside `ResearchRetriever`.

## What Changes

- Extract sparse lexical recall into `business.research.rag.retrieval.channels.sparse_lexical`.
- Preserve current BM25 index behavior, `list_chunks` fallback, degradation trace, sparse metadata, and formula sparse fallback.
- Keep `ResearchRetriever` as the orchestrator for this slice; it delegates sparse recall to the channel.
- Add focused channel tests plus existing retriever parity coverage.

## Capabilities

### New Capabilities

- `paper-rag-sparse-lexical-channel`: Sparse lexical recall is implemented as a reusable recall channel.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/sparse_lexical.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval channel tests
- No intended behavior change to `RetrievalResult` or tuned policy scores.
