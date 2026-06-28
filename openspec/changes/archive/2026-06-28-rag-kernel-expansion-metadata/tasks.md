## 1. Kernel Expansion Metadata

- [x] 1.1 Add `framework/rag/retrieval/expansion.py`
- [x] 1.2 Add an `ExpansionMetadata` value object
- [x] 1.3 Add an `expansion_metadata()` helper returning standard expansion provenance keys
- [x] 1.4 Export expansion helpers from `framework/rag/retrieval`

## 2. Research Wiring

- [x] 2.1 Rewire Research `_with_expansion_metadata()` to call the kernel helper
- [x] 2.2 Preserve existing `expanded_from_chunk_id`, `expansion_reason`, `expansion_edge`, and `expansion_rank` keys
- [x] 2.3 Keep Paper-specific expansion rules in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-expansion-metadata --strict`
- [x] 3.2 Run framework expansion and Research retriever tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
