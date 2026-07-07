## Why

PRD 16 expects table-related context expansion to live outside `ResearchRetriever`. After extracting child scoring, `_supplemental_table_hits` can now move into a dedicated expander without keeping a scoring dependency inside the retriever.

## What Changes

- Add `SupplementalTableHitExpander` under `business.research.rag.retrieval.expanders.supplemental_table`.
- Move supplemental table retrieval, scoring, and metadata tagging out of `paper_retriever.py`.
- Update `ResearchRetriever` to delegate supplemental table hit injection to the new expander.
- Preserve result-intent gating, table deduplication, scorer metadata, and `supplemental_reason`.
- Add focused supplemental table expander tests.

## Capabilities

### New Capabilities

- `paper-rag-supplemental-table-hit-expander`: Paper RAG retrieval can inject supplemental table hits through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/supplemental_table.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/expanders/__init__.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No intended behavior change to supplemental table retrieval output or metadata.
