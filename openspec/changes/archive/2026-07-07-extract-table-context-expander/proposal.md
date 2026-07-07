## Why

PRD 16 requires table context expansion to be a dedicated expander rather than retriever-internal logic. The current `_fetch_table_context` block owns nearby references, body references, row-group parent tables, parent section context, result/conclusion context search, and optional reranking.

## What Changes

- Add `TableContextExpander` under `business.research.rag.retrieval.expanders.table_context`.
- Move `_fetch_table_context`, result-context candidate selection, table-context rerank, and table-context helper functions out of `paper_retriever.py`.
- Update `ResearchRetriever` to delegate table ref chunk expansion to `TableContextExpander`.
- Keep supplemental table child injection in `ResearchRetriever` for now because it depends on child scoring.
- Preserve table expansion metadata, source locator inheritance, result paragraph filtering, and rerank metadata.

## Capabilities

### New Capabilities

- `paper-rag-table-context-expander`: Paper RAG retrieval can expand table chunks into nearby/result context through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/table_context.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/expanders/__init__.py`
  - retrieval tests
- No intended behavior change to `RetrievalResult.ref_chunks`, table context ordering, or table context metadata.
