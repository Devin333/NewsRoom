## 1. Retrieval Kernel Utilities

- [x] 1.1 Add `framework/rag/retrieval` package exports
- [x] 1.2 Implement weighted score fusion for `RAGEvidence` and `RAGScoreBreakdown`
- [x] 1.3 Implement deterministic lexical field scoring with best-field metadata
- [x] 1.4 Implement evidence deduplication by chunk id with highest-score retention

## 2. Context Kernel Utilities

- [x] 2.1 Add `framework/rag/context` package exports
- [x] 2.2 Implement context budget trimming without mutating evidence provenance
- [x] 2.3 Implement citation resolution for `main_span` and `overlap_spans`
- [x] 2.4 Implement a basic context assembler that sorts, dedupes, and budgets evidence

## 3. Tests and Verification

- [x] 3.1 Add retrieval scoring, field scoring, and dedup tests
- [x] 3.2 Add context budget, citation, and assembler tests
- [x] 3.3 Run `openspec validate rag-kernel-context-retrieval --strict`
- [x] 3.4 Run compile and targeted pytest for framework RAG, Research RAG, and Harness RAG
