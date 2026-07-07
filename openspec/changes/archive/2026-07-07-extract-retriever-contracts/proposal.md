## Why

`business/research/rag/retrieval/paper_retriever.py` is still over 500 lines after the retrieval stage extractions because it owns three unrelated concerns: policy definitions, request/result DTOs, and the thin `ResearchRetriever` wiring entrypoint. PRD 16 expects `paper_retriever.py` to become a small entrypoint, so the reusable contracts need their own modules before the final wiring cleanup.

## What Changes

- Move `RetrievalPolicy`, policy constants, and policy builders into `retrieval/policies.py`.
- Move `RetrievalRequest` and `RetrievalResult` into `retrieval/contracts.py`.
- Keep compatibility re-exports from `paper_retriever.py` and the retrieval package so existing imports do not break.
- Update retrieval internals to import the contracts from the new ownership modules where practical.
- Add focused tests that guard the compatibility exports and evidence-candidate conversion.

## Capabilities

### New Capabilities

- `paper-rag-retriever-contract-modules`: Paper RAG retrieval contracts are owned by dedicated modules instead of the retriever wiring entrypoint.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/contracts.py`
  - `business/research/rag/retrieval/policies.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No retrieval behavior, policy values, or result schema changes are intended.
