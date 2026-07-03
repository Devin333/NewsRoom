## Why

PRD 16 requires `ResearchRetriever` to become a thin entrypoint that delegates to an explicit retrieval pipeline. The retriever already delegates recall, rerank scoring, and context expansion to stage objects, but `retrieve()` still owns the full orchestration and metrics assembly, keeping the file large and making the future pipeline boundary hard to verify.

## What Changes

- Add `RetrievalPipeline` under `business.research.rag.retrieval.pipeline`.
- Move the current `ResearchRetriever.retrieve()` orchestration into the pipeline without changing retrieval behavior or result metadata.
- Update `ResearchRetriever` to construct stage dependencies and delegate `retrieve()` to the pipeline.
- Export `RetrievalPipeline` from the retrieval package.
- Add focused parity tests proving the entrypoint delegates to the pipeline and preserves existing retrieval metadata.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-pipeline-entrypoint`: Paper RAG retrieval can execute through an explicit pipeline entrypoint while preserving the existing `ResearchRetriever` contract.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/pipeline.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No API or metadata contract changes are intended.
