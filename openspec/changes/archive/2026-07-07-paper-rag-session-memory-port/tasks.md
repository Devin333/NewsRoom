## 1. Memory Port Wiring

- [x] 1.1 Add a Research RAG `MemoryRuntime` to `MemoryPort` adapter.
- [x] 1.2 Add optional memory injection to `PaperRAGSession`.
- [x] 1.3 Add opt-in factory wiring behind `NEWS_RAG_MEMORY`.

## 2. Namespace Safety

- [x] 2.1 Persist `MemoryRecord.namespace` and `tenant_id` in vector memory payloads.
- [x] 2.2 Filter vector memory search by query namespace and tenant id.

## 3. Tests And Validation

- [x] 3.1 Add adapter, session, factory, and vector namespace tests.
- [x] 3.2 Run targeted tests, compile, smoke/full checks, and strict OpenSpec validation.
