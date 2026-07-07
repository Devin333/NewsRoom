## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for rerank cascade extraction.

## 2. Rerank Cascade

- [x] 2.1 Add `retrieval/rerank.py` with `RerankCascade` and field passage formatting.
- [x] 2.2 Update `ResearchRetriever` to delegate base and field rerank score calculation to `RerankCascade`.
- [x] 2.3 Export the rerank cascade from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add unit tests for base reranker success/fallback and field reranker success/fallback.
- [x] 3.2 Run targeted retrieval tests, compile checks, and `openspec validate extract-rerank-cascade --strict`.
