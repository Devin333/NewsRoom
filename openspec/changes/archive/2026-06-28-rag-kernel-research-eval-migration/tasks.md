## 1. Candidate-Aware Generic Metrics

- [x] 1.1 Extend `RetrievalMetricCase` with ranked evidence id candidate groups
- [x] 1.2 Extend `RetrievalMetricCase` with ranked source locator candidate groups
- [x] 1.3 Keep existing single-id metric behavior compatible
- [x] 1.4 Add framework tests for candidate id and locator scoring

## 2. Research Evaluation Wiring

- [x] 2.1 Convert `EvidenceSampleResult` into `RetrievalMetricCase` during aggregation
- [x] 2.2 Use framework Hit@K, reciprocal rank, evidence coverage, source locator coverage, and nDCG in `EvidenceEvalResult` aggregation
- [x] 2.3 Keep paper-specific type, image, visual, citation, overlap, and over-retrieval metrics in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-research-eval-migration --strict`
- [x] 3.2 Run framework RAG, Research RAG, and Harness RAG pytest coverage
- [x] 3.3 Run compile and import-boundary scans
