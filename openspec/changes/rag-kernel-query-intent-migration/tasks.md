## 1. Kernel Query Intent

- [x] 1.1 Add `framework/rag/retrieval/query_intent.py`
- [x] 1.2 Add `QueryIntentRule` validation
- [x] 1.3 Add deterministic first-match query intent classification
- [x] 1.4 Export query intent helpers from `framework/rag/retrieval`

## 2. Research Wiring

- [x] 2.1 Rewire Research `classify_query_intent()` to use kernel rule matching
- [x] 2.2 Keep Paper-specific intent names, rule order, filters, and route construction in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-query-intent-migration --strict`
- [x] 3.2 Run framework query intent tests and Research routing tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
