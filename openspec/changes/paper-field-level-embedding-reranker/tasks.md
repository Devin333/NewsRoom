## 1. OpenSpec And Design

- [x] 1.1 Create proposal, design, tasks, and capability spec for field-level embedding retrieval.
- [x] 1.2 Validate the change with `openspec validate paper-field-level-embedding-reranker --strict`.

## 2. Field Text And Indexing

- [x] 2.1 Add reusable `PaperChunk` field text extraction utilities.
- [x] 2.2 Add field embedding index/search ports.
- [x] 2.3 Add vector-store-backed field chunk index infrastructure.
- [x] 2.4 Wire optional field indexing into `ChunkPaperPipeline` and composition root.

## 3. Retrieval Fusion

- [x] 3.1 Add retrieval policy fields for field search plans and final/fallback score weights.
- [x] 3.2 Merge field vector hits with base chunk candidates by `chunk_id`.
- [x] 3.3 Add structured field reranking through an optional field reranker.
- [x] 3.4 Compute field embedding, field rerank, graph, and final score metadata.
- [x] 3.5 Preserve deterministic fallback behavior when field index or field reranker is absent or fails.
- [x] 3.6 Expose new metadata through evidence candidates and `EvidencePack`.

## 4. Tests

- [x] 4.1 Unit test field text extraction.
- [x] 4.2 Unit test field vector indexing and search.
- [x] 4.3 Unit test figure/table/formula/contribution intent field search behavior.
- [x] 4.4 Unit test field hit merge, structured reranker influence, and fallback behavior.
- [x] 4.5 Unit test evidence pack metadata propagation.
- [x] 4.6 Regression test parent/table/visual expansion still works with field-level retrieval enabled.

## 5. Verification

- [x] 5.1 Run focused research RAG tests.
- [x] 5.2 Run compile check.
- [x] 5.3 Validate OpenSpec strict after implementation tasks are complete.
