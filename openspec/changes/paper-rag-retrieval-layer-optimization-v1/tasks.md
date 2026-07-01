## 1. Metrics And Promotion Reporting

- [x] 1.1 Add explicit `@3` and `@5` retrieval values to benchmark JSON/markdown summaries.
- [x] 1.2 Add staged promotion checks for `Hit@3`, `Hit@5`, `evidence coverage@5`, and `source locator coverage@5`.
- [x] 1.3 Add or update tests proving reports expose `@3/@5/@10` without recalculating metrics.

## 2. Hybrid Retrieval Policy

- [x] 2.1 Add a named `paper_hybrid_rrf_rag_v1` retrieval policy without changing default behavior.
- [x] 2.2 Implement deterministic sparse lexical candidate recall over Paper chunks.
- [x] 2.3 Implement multi-query variants and RRF-style channel fusion for hybrid policy candidates.
- [x] 2.4 Preserve sparse/RRF/channel contribution metadata in returned child chunks.
- [x] 2.5 Add tests showing sparse/RRF recall can surface exact term evidence missed by primary semantic ranking.

## 3. Evidence Graph And Locator Preservation

- [x] 3.1 Strengthen table/result/figure/formula graph expansion metadata and caps.
- [x] 3.2 Preserve or inherit source locators on expanded, supplemental, parent, and snippet chunks.
- [x] 3.3 Add tests for locator inheritance and graph expansion metadata.

## 4. Validation

- [x] 4.1 Run targeted Paper RAG retrieval/evaluation tests.
- [x] 4.2 Run `openspec validate paper-rag-retrieval-layer-optimization-v1 --strict`.
- [x] 4.3 Run compile checks.
- [x] 4.4 Commit completed implementation changes.
