## Why

The PRD calls for `framework/rag/retrieval/rerank.py`. Research currently owns generic reranker score handling: validating the number of scores, clamping scores into a safe range, mapping scores back to candidate ids, and building deterministic sort keys. These operations are domain-neutral and should be reusable across RAG adapters while keeping Paper-specific query and passage construction in Research.

## What Changes

- Add `framework/rag/retrieval/rerank.py`.
- Introduce `RerankScoreSet` for score count validation, score clamping, id mapping, and threshold filtering.
- Introduce `rerank_sort_key()` for deterministic rerank ordering.
- Rewire Research base, field, table-context, and parent-context reranker score handling to use the kernel helpers.
- Keep Paper-specific reranker query strings, passage construction, policy gating, metadata names, and expansion behavior in Research.

## Capabilities

### New Capabilities

- `rag-kernel-rerank-score-handling`: domain-neutral reranker score validation, normalization, id mapping, threshold filtering, and sort key generation.

### Modified Capabilities

- `paper-rag-rerank-score-migration`: Paper retriever delegates generic reranker score handling to the RAG kernel while preserving Paper-specific rerank behavior.

## Impact

Affected code is limited to `framework/rag/retrieval`, `ResearchRetriever` rerank score handling, targeted tests, and this OpenSpec change. Existing Paper retrieval tests define the expected ordering and metadata compatibility.
