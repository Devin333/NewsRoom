## 1. Port And Adapter Contract

- [x] 1.1 Add `list_chunks(paper_id: str) -> list[PaperChunk]` to `ChunkStorePort`.
- [x] 1.2 Add `list_paper_payloads(paper_id: str) -> list[dict[str, Any]]` to `ChunkPayloadStorePort`.
- [x] 1.3 Implement `PaperChunkStoreAdapter.list_chunks` by converting payload-store results.
- [x] 1.4 Implement Qdrant-backed paper payload listing and in-memory vector-store support.

## 2. Retriever Wiring

- [x] 2.1 Replace sparse lexical candidate inventory lookup with direct `self._store.list_chunks`.
- [x] 2.2 Replace formula reverse-context inventory lookup with direct `self._store.list_chunks`.
- [x] 2.3 Remove `_list_store_chunks` reflection fallback.
- [x] 2.4 Add retrieval metadata degradation when sparse is enabled but chunk inventory is empty.

## 3. Tests And Validation

- [x] 3.1 Add or update tests proving `PaperChunkStoreAdapter.list_chunks` works with the vector payload store.
- [x] 3.2 Add or update tests proving sparse recall works without private chunk dictionary reflection.
- [x] 3.3 Add or update tests proving empty sparse inventory is observable.
- [x] 3.4 Run targeted tests, `openspec validate fix-sparse-channel-production-wiring --strict`, and compile checks.
