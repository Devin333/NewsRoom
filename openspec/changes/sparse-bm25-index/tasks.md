## 1. BM25 Index

- [x] 1.1 Add OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Implement dependency-free BM25 index build, query, serialize, and load helpers.
- [x] 1.3 Add default per-paper BM25 index path helper.

## 2. Ingest And Retrieval Wiring

- [x] 2.1 Write BM25 index from `ChunkPaperPipeline` after manifest-stable chunk ids are resolved.
- [x] 2.2 Update sparse lexical recall to prefer persisted BM25 index.
- [x] 2.3 Add observable fallback when BM25 index is missing or unreadable.

## 3. Tests And Validation

- [x] 3.1 Add BM25 ranking and persistence tests.
- [x] 3.2 Add chunk pipeline test proving BM25 index artifact is written.
- [x] 3.3 Add retriever test proving sparse recall uses BM25 fallback/index path.
- [x] 3.4 Run retrieval/application tests, compile checks, and `openspec validate sparse-bm25-index --strict`.
