## Why

PRD 16 requires context expansion to move out of `paper_retriever.py` into explicit expander modules. Parent context expansion is currently a large self-contained block in `ResearchRetriever`, so extracting it is the safest first expander slice.

## What Changes

- Add `business.research.rag.retrieval.expanders` package.
- Add `ParentContextExpander` that owns parent candidate discovery, parent scoring, reranker-assisted parent ordering, token budgeting, and child-anchored snippets.
- Update `ResearchRetriever` to delegate parent expansion to `ParentContextExpander`.
- Preserve existing parent metadata, scoring, budgets, fallback behavior, and returned `parent_metrics`.
- Add focused parent expander tests and keep retriever parent-context tests passing.

## Capabilities

### New Capabilities

- `paper-rag-parent-context-expander`: Paper RAG retrieval can expand child hits into parent context through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/base.py`
  - `business/research/rag/retrieval/expanders/parent.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval tests
- No intended behavior change to parent chunk ordering, parent snippet metadata, token budget metrics, or evidence pack metadata.
