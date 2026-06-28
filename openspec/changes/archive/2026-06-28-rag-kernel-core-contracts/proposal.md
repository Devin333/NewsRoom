## Why

`business/research/rag` now owns both paper-specific semantics and reusable RAG contracts, which makes future RAG reuse outside Research depend on paper models. We need a first migration slice that introduces domain-neutral `framework/rag` contracts and a Paper adapter without changing retrieval ranking behavior.

## What Changes

- Add a new `framework/rag/core` package for domain-neutral RAG DTOs and ports.
- Add typed contracts for `RAGChunk`, `RAGQuery`, `RAGEvidence`, `SourceLocator`, and score breakdown metadata.
- Add paper-side adapter utilities that project `business.research.document.models.PaperChunk` into framework RAG contracts.
- Add import-boundary tests proving `framework/rag` does not depend on `business.research` or paper parsing concepts.
- Keep existing Research retriever algorithms, benchmark behavior, and CLI entrypoints unchanged in this first slice.

## Capabilities

### New Capabilities

- `rag-kernel-core`: introduces domain-neutral RAG contracts and ports under `framework/rag/core`.
- `paper-rag-kernel-adapter`: introduces the Research-owned adapter boundary that maps Paper chunks into framework RAG contracts.

### Modified Capabilities

- None

## Impact

Affected code includes a new `framework/rag` package, new `business/research/rag/adapters` code, and targeted tests under `tests/framework/rag` and `tests/business/research/rag/adapters`. Existing Paper RAG retrieval, benchmark scoring, visual processing, and Harness RAG orchestration remain behaviorally unchanged.
