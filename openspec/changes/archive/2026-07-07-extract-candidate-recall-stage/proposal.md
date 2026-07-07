## Why

PRD 16 requires retrieval to be organized as explicit pipeline stages. `ResearchRetriever.retrieve()` still owns the candidate recall stage: dense/sparse recall, field/claim/visual recall, hit merging, and hybrid RRF fusion.

## What Changes

- Add `CandidateRecallStage` under `business.research.rag.retrieval.recall_stage`.
- Move text recall, hybrid dense+sparse recall, field/claim/visual hit lookup, field/claim hit merging, visual hit capture, and hybrid RRF candidate fusion out of `paper_retriever.py`.
- Return a structured `CandidateRecallResult` with candidates, field hits, claim hits, visual hits, recall counts, and query variants.
- Update `ResearchRetriever` to consume `CandidateRecallResult` and preserve existing metrics.
- Add focused candidate recall stage tests.

## Capabilities

### New Capabilities

- `paper-rag-candidate-recall-stage`: Paper RAG retrieval can run candidate recall through a dedicated stage module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/recall_stage.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No intended behavior change to candidate recall, hybrid RRF metadata, or retrieval metrics.
