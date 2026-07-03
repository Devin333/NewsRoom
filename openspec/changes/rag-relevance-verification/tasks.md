## 1. Framework Relevance Verification

- [x] 1.1 Add `RelevanceScorerPort` and `RAGRelevanceGate` under `framework/harness/rag`.
- [x] 1.2 Extend `SourceVerifier` with optional relevance scorer, question argument, low-relevance rejection metadata, and relevance gate results.
- [x] 1.3 Export relevance symbols from `framework/harness/rag/__init__.py`.

## 2. Session Gap Reporting

- [x] 2.1 Pass `spec.goal.question` into source verification from `BoundedRAGSessionController`.
- [x] 2.2 Add `rejection_summary` to `_gap_report` with reason and evidence-type counts.
- [x] 2.3 Preserve current no-scorer behavior for existing source verification decisions.

## 3. Tests

- [x] 3.1 Add unit tests for `RAGRelevanceGate`.
- [x] 3.2 Add unit tests for `SourceVerifier` relevance accept/reject/no-scorer compatibility.
- [x] 3.3 Add session controller tests proving low relevance triggers a gap summary and controlled replan/insufficient evidence.

## 4. Validation

- [x] 4.1 Run targeted framework RAG tests.
- [x] 4.2 Run compile and strict OpenSpec validation.
- [x] 4.3 Commit the completed T2 slice.
