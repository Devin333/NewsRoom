## Why

The enterprise RAG review notes that production `PaperRAGSession` does not pass a `MemoryPort` to `BoundedRAGSessionController`, so RAG memory recall always falls through the `"memory port is not configured"` branch. Framework memory runtime and vector memory storage already exist, but the production paper RAG composition root does not connect them.

## What Changes

- Add a Research RAG memory adapter that maps `MemoryRuntime.recall()` results into the harness `MemoryPort` hit shape.
- Add `memory` injection to `PaperRAGSession` and pass it into `BoundedRAGSessionController`.
- Add an opt-in `NEWS_RAG_MEMORY` factory path that builds a vector-backed episodic memory port for paper RAG sessions.
- Preserve current behavior when `NEWS_RAG_MEMORY` is unset or false.
- Persist and filter `MemoryRecord.namespace` in the vector memory store so RAG memory recall respects allowed namespaces.

## Capabilities

### New Capabilities

- `paper-rag-session-memory-port`: Paper RAG sessions can recall bounded episodic memory through the harness `MemoryPort`.

## Impact

- Affected Research RAG session composition: `business/research/application/paper_rag_session.py`.
- Affected production factory: `interfaces/services/paper_rag_factory.py`.
- Affected Research RAG adapters: `business/research/rag/adapters`.
- Affected vector memory storage: `infrastructure/storage/memory/vector_memory_store.py`.
- No default production behavior change unless `NEWS_RAG_MEMORY` is enabled.
