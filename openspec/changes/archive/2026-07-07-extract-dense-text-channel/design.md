## Context

The retriever still calls `ChunkStorePort.search_with_scores` directly in both normal text recall and hybrid RRF recall. Extracting this direct call into a channel continues the PRD 16 channel migration without changing planning, fusion, rerank, or expansion.

## Goals / Non-Goals

**Goals:**

- Move dense text search ownership into a channel class.
- Keep the current chunk-shaped compatibility method for the existing retriever.
- Expose `recall(...) -> RankedList` for the target channel contract.

**Non-Goals:**

- Do not move multi-query planning out of `ResearchRetriever`.
- Do not change overfetch, RRF, or candidate filters.
- Do not extract field embedding, claim, visual, rerank, or expanders in this slice.

## Decisions

- **Exception behavior:** `recall_chunks(..., suppress_errors=False)` preserves direct search failures for non-hybrid paths. Hybrid RRF passes `suppress_errors=True` to preserve the existing warning-and-continue behavior.
- **Metadata:** Dense text channel does not add new metadata in this slice because existing downstream code treats the raw semantic score as the dense signal.

## Risks / Trade-offs

- The retriever still owns query/filter loops after this slice. That is intentional so behavior stays stable while channel classes are introduced one at a time.
