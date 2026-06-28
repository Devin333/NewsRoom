## Why

Research retrieval and evidence evaluation still reimplement simple chunk deduplication, while `framework/rag/retrieval` already owns evidence dedup utilities. Chunk-level deduplication by a stable key is domain-neutral and should be reusable by other RAG adapters without importing Paper models.

## What Changes

- Add generic `dedupe_by_key()` to `framework/rag/retrieval`.
- Keep existing `dedupe_evidence()` behavior unchanged: evidence duplicates still keep the highest score for each key.
- Rewire Research chunk deduplication in `ResearchRetriever` and evidence evaluation to use `dedupe_by_key()`.
- Keep Paper-specific expansion, table/formula/visual references, and ranking behavior unchanged.
- Add framework unit coverage for first-seen deduplication.

## Capabilities

### New Capabilities

- `rag-kernel-keyed-dedup`: domain-neutral first-seen deduplication for arbitrary RAG adapter values.

### Modified Capabilities

- `paper-rag-dedup-migration`: Paper retrieval/evaluation deduplicates chunks through kernel primitives while preserving existing chunk order.

## Impact

Affected code is limited to `framework/rag/retrieval`, Research dedup call sites, targeted tests, and this OpenSpec change. No ranking, expansion, benchmark generation, or report output behavior should change.
