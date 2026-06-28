## 1. Scorecard Adapter

- [x] 1.1 Add a Research adapter for evidence result to `RAGScorecard` projection
- [x] 1.2 Include retrieval, answer, and generation metrics as `MetricValue` entries
- [x] 1.3 Preserve paper-specific metrics in scorecard metadata
- [x] 1.4 Map known Research failure reasons into `RAGFailureReason`

## 2. Report Integration

- [x] 2.1 Add `rag_evaluation_report` to `EvidenceRegressionReport.to_dict()`
- [x] 2.2 Add a RAG Scorecard markdown section without removing existing Research report sections
- [x] 2.3 Keep threshold and issue behavior unchanged

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-research-scorecard-report --strict`
- [x] 3.2 Run targeted report tests
- [x] 3.3 Run framework RAG, Research RAG, Harness RAG pytest coverage, compile, and boundary scans
