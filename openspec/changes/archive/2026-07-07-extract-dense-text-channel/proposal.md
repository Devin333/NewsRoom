## Why

PRD 16 calls for dense text, sparse lexical, field embedding, claim, and visual recall to become homogeneous channels. Sparse lexical is now extracted; dense text is the next safest adjacent recall source because it already returns `list[tuple[PaperChunk, score]]` from `ChunkStorePort.search_with_scores`.

## What Changes

- Add `DenseTextChannel` under `business.research.rag.retrieval.channels`.
- Delegate semantic text search calls from `ResearchRetriever` to the channel.
- Preserve current non-hybrid exception behavior and hybrid warning/fallback behavior.
- Add focused dense channel tests.

## Capabilities

### New Capabilities

- `paper-rag-dense-text-channel`: Dense text recall is implemented as a reusable recall channel.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/dense_text.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval channel tests
- No intended behavior change to retrieval ranking or metadata.
