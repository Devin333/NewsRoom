## 1. Specification

- [x] 1.1 Validate the OpenSpec change artifacts.

## 2. Boundary Fix

- [x] 2.1 Remove `interfaces.services.paper_rag_service` imports from `run_evidence_eval.py`.
- [x] 2.2 Build fixture-backed live answer eval from `PaperRAGSession` and business RAG adapters directly.
- [x] 2.3 Return a clear error for default live answer eval when no parsed chunks or injected ask callable are available.

## 3. Tests

- [x] 3.1 Add regression coverage for the no-fixture live answer eval error.
- [x] 3.2 Verify live answer eval conversion tests still pass.
- [x] 3.3 Verify architecture boundary tests pass.
