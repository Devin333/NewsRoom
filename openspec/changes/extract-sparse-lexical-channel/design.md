## Context

The channel contract from `refactor-retrieval-pipeline-channels` already exists. This change uses it for the first real recall source extraction: sparse lexical recall.

## Goals / Non-Goals

**Goals:**

- Move sparse lexical BM25 recall and formula sparse fallback out of `ResearchRetriever`.
- Keep observable degradations and metadata stable.
- Provide a channel API that later pipeline work can call directly.

**Non-Goals:**

- Do not extract dense, field, claim, visual, rerank, or expander logic in this slice.
- Do not change ranking weights, policy values, or query planning.
- Do not remove compatibility chunk-shaped return helpers yet.

## Decisions

- **Chunk-shaped compatibility:** The channel exposes `recall_chunks(...) -> list[tuple[PaperChunk, float]]` for the current retriever and `recall(...) -> RankedList` for the target channel contract.
- **Trace injection:** The channel accepts `RetrievalTrace | None` and records the same degradation codes used by the retriever.
- **Formula fallback stays local:** Formula sparse fallback remains inside the sparse channel because it supplements lexical/BM25 recall rather than downstream reranking.

## Risks / Trade-offs

- Some formula helper functions move with the sparse channel even though child reranking still needs formula scoring. To avoid behavior drift, the scorer is exported and reused by the retriever.
- The retriever remains large after this slice; this is an incremental extraction toward the PRD target.
