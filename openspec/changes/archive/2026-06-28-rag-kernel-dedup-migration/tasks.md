## 1. Kernel Dedup Primitive

- [x] 1.1 Add `dedupe_by_key()` to `framework/rag/retrieval`
- [x] 1.2 Export `dedupe_by_key()` from the retrieval package
- [x] 1.3 Add framework test coverage for first-seen keyed deduplication
- [x] 1.4 Preserve existing `dedupe_evidence()` highest-score behavior

## 2. Research Wiring

- [x] 2.1 Rewire `ResearchRetriever` chunk deduplication to use `dedupe_by_key()`
- [x] 2.2 Rewire evidence evaluation ranked chunk deduplication to use `dedupe_by_key()`
- [x] 2.3 Keep Paper-specific expansion and scoring behavior unchanged

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-dedup-migration --strict`
- [x] 3.2 Run targeted framework dedup and Research retrieval/evaluation tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
