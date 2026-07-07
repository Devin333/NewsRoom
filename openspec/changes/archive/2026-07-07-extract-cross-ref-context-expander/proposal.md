## Why

PRD 16 calls for context expanders to be explicit modules. Cross-reference expansion is currently embedded in `ResearchRetriever` and handles first-level chunk references, page visual related chunks, figure references, and formula reverse context. Extracting it reduces retriever coupling while keeping table context expansion untouched.

## What Changes

- Add `CrossRefContextExpander` under `business.research.rag.retrieval.expanders.cross_ref`.
- Move `_fetch_refs` cross-reference logic and its figure/formula reference helpers out of `paper_retriever.py`.
- Update `ResearchRetriever` to delegate ref chunk expansion to the new expander.
- Preserve existing expansion metadata, source locator inheritance, and deduplication behavior.
- Add focused tests for chunk references, page visual related chunks, figure refs, and formula reverse refs.

## Capabilities

### New Capabilities

- `paper-rag-cross-ref-context-expander`: Paper RAG retrieval can expand child hits into cross-reference context through a dedicated expander module.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/expanders/cross_ref.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/expanders/__init__.py`
  - retrieval tests
- No intended behavior change to `RetrievalResult.ref_chunks` or expansion metadata.
