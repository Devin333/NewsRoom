## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for removing orphan hybrid search.

## 2. Removal

- [x] 2.1 Delete `infrastructure/storage/hybrid_search.py`.
- [x] 2.2 Delete `tests/infrastructure/storage/test_hybrid_search.py`.
- [x] 2.3 Update active storage spec to remove the orphan storage-layer hybrid search requirement.
- [x] 2.4 Verify no non-archived code references `HybridSearchService`, `HybridSearchQuery`, or `infrastructure.storage.hybrid_search`.

## 3. Tests And Validation

- [x] 3.1 Run relevant storage tests, RAG tests, compile checks, and `openspec validate remove-orphan-hybrid-search --strict`.
