## Why

PRD 16 requires `RetrievalPipeline` to stay small and stage-oriented, but after extracting the entrypoint it still owns a large metadata dictionary and helper functions. Moving metrics assembly into a dedicated builder keeps the pipeline focused on orchestration and preserves the existing metadata contract.

## What Changes

- Add `RetrievalMetricsBuilder` under `business.research.rag.retrieval.metrics`.
- Move retrieval result metadata assembly and related helper functions out of `pipeline.py`.
- Update `RetrievalPipeline` to call the metrics builder with explicit stage outputs.
- Export `RetrievalMetricsBuilder` from the retrieval package.
- Add focused tests for key metadata fields and trace preservation.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-metrics-builder`: Paper RAG retrieval metadata can be assembled by a dedicated metrics builder while preserving existing result metadata fields.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/metrics.py`
  - `business/research/rag/retrieval/pipeline.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No behavior, scoring, policy, or result schema changes are intended.
