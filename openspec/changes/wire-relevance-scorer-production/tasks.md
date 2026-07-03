## 1. Production Relevance Scorer Wiring

- [x] 1.1 Add `RerankerRelevanceScorer` under `business/research/rag/adapters`.
- [x] 1.2 Allow `PaperRAGSession` to receive a relevance scorer and pass it to `SourceVerifier`.
- [x] 1.3 Wire the scorer in `interfaces/services/paper_rag_factory.py` when reranking is enabled.

## 2. Policy Thresholds

- [x] 2.1 Add default `min_relevance` to the research RAG source policy.
- [x] 2.2 Add `min_relevance_by_type` support for formula/table evidence.
- [x] 2.3 Make `SourceVerifier` apply per-evidence-type thresholds while preserving existing behavior.

## 3. Tests

- [x] 3.1 Add unit coverage for reranker score normalization.
- [x] 3.2 Add session/factory tests proving production scorer injection.
- [x] 3.3 Add source verifier coverage for evidence-type-specific thresholds.

## 4. Validation

- [x] 4.1 Run targeted RAG and service tests.
- [x] 4.2 Run compile and strict OpenSpec validation.
- [x] 4.3 Run the project smoke/full test suite before commit.
