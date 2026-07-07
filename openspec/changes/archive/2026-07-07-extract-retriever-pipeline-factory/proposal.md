## Why

After moving retrieval contracts and policy definitions out of `paper_retriever.py`, the remaining entrypoint is still above PRD 16's target because it constructs every retrieval channel, stage, expander, and pipeline inline. The entrypoint should be a small adapter around a configured pipeline, while the composition root should own construction details.

## What Changes

- Add `retrieval/factory.py` with `build_retrieval_pipeline(...)`.
- Move channel, stage, expander, reranker cascade, and pipeline construction out of `ResearchRetriever.__init__`.
- Keep `ResearchRetriever` public behavior and constructor parameters unchanged.
- Add a focused test that proves the factory path remains compatible with `ResearchRetriever`.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-pipeline-factory`: Paper RAG retrieval can build the composed retrieval pipeline through a dedicated factory while keeping `ResearchRetriever` as a thin entrypoint.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/factory.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No retrieval scoring, policy, or result schema changes are intended.
