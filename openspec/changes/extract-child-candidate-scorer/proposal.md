## Why

PRD 16 requires retrieval scoring to become explicit pipeline modules. `ResearchRetriever` still owns child candidate scoring, field-score metadata assembly, formula/citation boosts, and route-match metadata, which keeps the retriever large and blocks moving supplemental table retrieval into an expander.

## What Changes

- Add `ChildCandidateScorer` under `business.research.rag.retrieval.scoring`.
- Move child candidate score calculation and its scoring helper types/functions out of `paper_retriever.py`.
- Update `ResearchRetriever` to delegate `_score_child_candidate` to the scorer while preserving metadata keys, score weights, boosts, and final score rounding.
- Keep policy values and retrieval behavior unchanged.
- Add focused scorer tests that compare field, citation, formula, route, and position scoring metadata.

## Capabilities

### New Capabilities

- `paper-rag-child-candidate-scorer`: Paper RAG retrieval can score child candidates through a dedicated scorer module with stable score metadata.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/scoring.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval tests
- No intended behavior change to `RetrievalResult.child_chunks`, child score metadata, or candidate ordering.
