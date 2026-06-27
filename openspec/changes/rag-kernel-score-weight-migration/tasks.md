## 1. Kernel Score Weighting

- [x] 1.1 Add generic score-weight normalization to `framework/rag/retrieval`
- [x] 1.2 Add generic weighted component scoring to `framework/rag/retrieval`
- [x] 1.3 Export the new utilities through the retrieval package
- [x] 1.4 Add framework unit tests for clamping, fallback, and missing component behavior

## 2. Research Wiring

- [x] 2.1 Rewire Research field score composition to use kernel weighted scoring
- [x] 2.2 Rewire Research child score composition to use kernel weighted scoring
- [x] 2.3 Rewire Research parent score composition to use kernel weighted scoring
- [x] 2.4 Keep Research policy weights, field extraction, graph scoring, visual scoring, and reranking behavior unchanged

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-score-weight-migration --strict`
- [x] 3.2 Run targeted framework retrieval and Research retriever tests
- [x] 3.3 Run full framework RAG, Research RAG, Harness RAG tests, compile, and boundary scans
