## Why

PRD 16 identifies `paper_retriever.py` as too large and too tightly coupled: recall sources return different shapes and fusion logic is embedded in the retriever. The next safe step is to introduce a common recall channel contract and move fusion into a single reusable module without changing retrieval behavior yet.

## What Changes

- Add shared `RankedHit`, `RankedList`, and `RecallChannel` protocol types.
- Move RRF fusion into `business.research.rag.retrieval.fusion`.
- Keep existing `ResearchRetriever` behavior by delegating the old internal RRF helper to the new fusion module.
- Add tests for deterministic RRF behavior and channel hit structure.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-channel-contract`: Paper RAG recall channels use a common ranked hit contract and a single fusion module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/base.py`
  - `business/research/rag/retrieval/fusion.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval unit tests
- No intended behavior change to `RetrievalResult`.
