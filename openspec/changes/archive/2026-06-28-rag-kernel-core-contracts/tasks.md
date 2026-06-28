## 1. Framework RAG Core Contracts

- [x] 1.1 Create `framework/rag` and `framework/rag/core` package exports
- [x] 1.2 Implement domain-neutral DTOs for `SourceLocator`, `RAGChunk`, `RAGQuery`, `RAGEvidence`, and `RAGScoreBreakdown`
- [x] 1.3 Implement protocol-style ports for chunk storage, retrieval, reranking, and context assembly

## 2. Paper RAG Adapter

- [x] 2.1 Create `business/research/rag/adapters` package
- [x] 2.2 Implement `PaperChunk` to `RAGChunk` projection with generic fields, metadata, and source locator preservation
- [x] 2.3 Implement `PaperChunk` to `RAGEvidence` projection with score breakdown extraction

## 3. Tests and Boundary Checks

- [x] 3.1 Add framework core DTO and protocol tests
- [x] 3.2 Add Paper adapter projection tests
- [x] 3.3 Add import-boundary tests proving `framework/rag` does not import Research or paper parser concepts

## 4. Verification

- [x] 4.1 Run `openspec validate rag-kernel-core-contracts --strict`
- [x] 4.2 Run compile and targeted pytest for framework RAG and Research RAG adapter coverage
- [x] 4.3 Confirm existing Paper RAG retrieval tests remain compatible
