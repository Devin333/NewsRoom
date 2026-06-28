## 1. Kernel Answer Scoring

- [x] 1.1 Add reusable `AnswerMetricScore`
- [x] 1.2 Add `score_answer_case()`
- [x] 1.3 Add generic fact coverage details, id coverage, locator coverage, and abstention helpers
- [x] 1.4 Preserve existing `evaluate_answer_case()` metric helper behavior

## 2. Research Wiring

- [x] 2.1 Convert `EvidenceAnswerSample` into `AnswerMetricCase`
- [x] 2.2 Delegate Research answer scoring to `score_answer_case()`
- [x] 2.3 Preserve Research `EvidenceAnswerScores`, report fields, failure reason strings, and `qa_type` aggregation

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-answer-eval-migration --strict`
- [x] 3.2 Run framework answer metric and Research answer eval tests
- [x] 3.3 Run full RAG pytest coverage, compile, and import-boundary scans
