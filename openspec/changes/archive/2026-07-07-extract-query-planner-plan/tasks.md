## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for query planner extraction.

## 2. Planner Extraction

- [x] 2.1 Add `retrieval/plan.py` with `RetrievalPlan`, `ChannelSpec`, `FusionSpec`, `RerankSpec`, and `ExpanderSpec`.
- [x] 2.2 Add `retrieval/planner.py` with `QueryPlanner` covering route, base filters, candidate filters, element labels, and candidate limit.
- [x] 2.3 Update `ResearchRetriever.retrieve()` to consume the planner output without changing ranking behavior.

## 3. Tests And Validation

- [x] 3.1 Add planner unit tests for formula sparse filters, element-label overfetch, citation overfetch, and route candidate filter groups.
- [x] 3.2 Run targeted retrieval tests, compile checks, and `openspec validate extract-query-planner-plan --strict`.
