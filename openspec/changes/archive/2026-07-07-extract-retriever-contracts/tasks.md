## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for retriever contract extraction.

## 2. Contract Modules

- [x] 2.1 Add `retrieval/policies.py` and move `RetrievalPolicy`, policy constants, and policy builder helpers into it.
- [x] 2.2 Add `retrieval/contracts.py` and move `RetrievalRequest`, `RetrievalResult`, and evidence-candidate conversion into it.
- [x] 2.3 Update `paper_retriever.py` to import contracts from the new modules and remain a compatibility re-export.
- [x] 2.4 Update package exports to expose the moved contracts from their new owners.

## 3. Tests And Validation

- [x] 3.1 Add focused tests for compatibility imports and `RetrievalResult.as_evidence_candidates()`.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-retriever-contracts --strict`.
