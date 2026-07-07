## Why

PRD 16 requires `paper_retriever.py` to shrink into a thin retrieval entrypoint, but query planning is still embedded in `ResearchRetriever.retrieve()` and private helpers. Extracting a serializable `RetrievalPlan` is the next safe refactor step because it separates intent/filter/limit planning from recall, rerank, and expansion execution without changing ranking behavior.

## What Changes

- Add `RetrievalPlan` and stage spec DTOs under `business.research.rag.retrieval.plan`.
- Add `QueryPlanner` under `business.research.rag.retrieval.planner`.
- Move current route/filter/candidate-limit planning into `QueryPlanner` while preserving existing policy values and retrieval behavior.
- Make `ResearchRetriever.retrieve()` consume the plan for route, candidate filters, element labels, and candidate limit.
- Add planner unit tests for formula, element-label overfetch, citation overfetch, and multi-filter route planning.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-query-planner`: Paper RAG retrieval can convert a retrieval request and policy into a serializable retrieval plan before recall execution.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/plan.py`
  - `business/research/rag/retrieval/planner.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval unit tests
- No intended behavior change to `RetrievalResult`, ranking scores, policy values, or downstream answer generation.
