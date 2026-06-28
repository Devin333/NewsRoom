## 1. Evaluation Kernel

- [x] 1.1 Add `framework/rag/evaluation` package exports
- [x] 1.2 Implement generic retrieval metric models and calculators
- [x] 1.3 Implement deterministic answer metric models and calculators
- [x] 1.4 Implement shared failure reason constants and report serialization

## 2. Harness Evidence Adapter

- [x] 2.1 Add Harness adapter for `RAGEvidence` to `EvidenceCandidate`
- [x] 2.2 Preserve source locator, score, score breakdown, and metadata in converted candidates
- [x] 2.3 Keep existing Harness session controller behavior unchanged

## 3. Tests and Verification

- [x] 3.1 Add retrieval metric and answer metric tests
- [x] 3.2 Add report and failure reason tests
- [x] 3.3 Add Harness evidence adapter tests
- [x] 3.4 Run `openspec validate rag-kernel-evaluation-harness-integration --strict`
- [x] 3.5 Run compile and targeted pytest for framework RAG, Research RAG, and Harness RAG
