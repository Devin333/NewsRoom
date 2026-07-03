## Why

PRD 16 calls for formula context expansion to be explicit and testable outside `paper_retriever.py`. Formula context currently lives in structural interleaving helpers, making formula nearby/parent/reverse context harder to evolve independently.

## What Changes

- Add `FormulaContextExpander` under `business.research.rag.retrieval.expanders.formula_context`.
- Move formula context reference extraction and formula-context question gating out of `paper_retriever.py`.
- Update `ResearchRetriever._structural_context_refs` to delegate formula refs to the expander.
- Preserve existing formula expansion reasons and per-policy max context limits.
- Add focused formula context expander tests.

## Capabilities

### New Capabilities

- `paper-rag-formula-context-expander`: Paper RAG retrieval can resolve formula nearby, parent, explicit, and reverse context through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/formula_context.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/expanders/__init__.py`
  - retrieval tests
- No intended behavior change to formula context chunk ordering or metadata.
