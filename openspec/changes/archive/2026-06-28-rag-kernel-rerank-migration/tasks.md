## 1. Kernel Rerank Helpers

- [x] 1.1 Add `framework/rag/retrieval/rerank.py`
- [x] 1.2 Add `RerankScoreSet` with length validation and score clamping
- [x] 1.3 Add score-to-id mapping and threshold helpers
- [x] 1.4 Add deterministic `rerank_sort_key()`
- [x] 1.5 Export rerank helpers from `framework/rag/retrieval`

## 2. Research Wiring

- [x] 2.1 Rewire base reranker score handling to use `RerankScoreSet`
- [x] 2.2 Rewire field reranker score mapping to use `RerankScoreSet`
- [x] 2.3 Rewire table-context reranker score handling and sorting to use kernel helpers
- [x] 2.4 Rewire parent-context reranker score validation to use `RerankScoreSet`
- [x] 2.5 Keep Paper-specific query/passage construction and metadata keys in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-rerank-migration --strict`
- [x] 3.2 Run framework rerank tests and Research retriever tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
