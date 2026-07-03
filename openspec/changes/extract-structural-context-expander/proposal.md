## Why

PRD 16 requires context expansion to be explicit modules. After parent, cross-ref, table, and formula helper extraction, `ResearchRetriever` still owns structural child interleaving for figure/table/formula nearby context.

## What Changes

- Add `StructuralContextExpander` under `business.research.rag.retrieval.expanders.structural`.
- Move `_interleave_structural_context`, figure/table structural refs, and expansion metadata helper logic out of `paper_retriever.py`.
- Update `ResearchRetriever` to delegate child structural interleaving to the new expander.
- Preserve existing child chunk ordering, deduplication, expansion metadata, and source locator inheritance.
- Add focused structural expander tests.

## Capabilities

### New Capabilities

- `paper-rag-structural-context-expander`: Paper RAG retrieval can interleave structural figure/table/formula context through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/structural.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/expanders/__init__.py`
  - retrieval tests
- No intended behavior change to `RetrievalResult.child_chunks` or expansion metadata.
