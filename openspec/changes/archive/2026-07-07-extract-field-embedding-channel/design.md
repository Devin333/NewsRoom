## Context

Field embedding recall is a mature recall source, but its implementation is split across `ResearchRetriever._search_field_candidates`, `_merge_field_hits`, `_field_hit_ranking`, and `_merge_field_embedding_hit`. This makes the retriever own channel-specific details that belong with the field embedding source.

## Goals / Non-Goals

**Goals:**

- Move field vector search and field hit adaptation into `FieldEmbeddingChannel`.
- Preserve the exact metadata fields used by downstream field scoring and reports.
- Preserve current warning-and-empty behavior when field embedding retrieval fails.

**Non-Goals:**

- Do not change field weights, field selection per intent, or reranker behavior.
- Do not move `_field_embedding_summary_from_metadata` or field final scoring in this slice.
- Do not extract visual channel logic in this slice.

## Decisions

- **Channel owns hit metadata:** `field_embedding_scores`, `field_embedding_hits`, `best_embedding_field`, and per-field score keys are channel-owned metadata.
- **Search still planned by retriever:** `ResearchRetriever` still decides enabled state, limits, candidate filters, and field names using current policy values.
- **Compatibility methods:** The channel exposes chunk-shaped merge and ranking helpers until the final pipeline uses `RankedHit` end to end.

## Risks / Trade-offs

- The retriever still imports `FieldEmbeddingHit` for type annotations and metrics. That is acceptable until all channel outputs use the target `RankedHit` shape.
