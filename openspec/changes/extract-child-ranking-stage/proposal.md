## Why

`RetrievalPipeline` still owns child ranking details: reranker thresholding, field rerank score lookup, child candidate scoring, visual score fusion, and final top-child selection. PRD 16 wants the pipeline to be a small stage orchestrator, so this ranking logic needs its own stage boundary.

## What Changes

- Add `ChildRankingStage` and `ChildRankingResult` under `business.research.rag.retrieval.ranking_stage`.
- Move candidate rerank filtering, field rerank scoring, child scoring, visual fusion, sorting, and top child selection out of `pipeline.py`.
- Update `RetrievalPipeline` to call the ranking stage and pass its result to context expanders and metrics.
- Export `ChildRankingStage` from the retrieval package.
- Add focused tests for threshold fallback, visual fusion, and result metadata compatibility.

## Capabilities

### New Capabilities

- `paper-rag-child-ranking-stage`: Paper RAG retrieval can rank recalled child candidates through a dedicated stage while preserving existing scoring behavior and metrics inputs.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/ranking_stage.py`
  - `business/research/rag/retrieval/pipeline.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No retrieval behavior, scoring weights, or result schema changes are intended.
