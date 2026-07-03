## 1. LLM Planner Worker

- [x] 1.1 Add an LLM-backed `ResearchCandidateWorkerPort` for RAG plan candidates.
- [x] 1.2 Add unit tests for valid planner JSON and invalid planner JSON failure behavior.

## 2. Production Factory Wiring

- [x] 2.1 Add `NEWS_RAG_LLM_PLANNER` truthy/falsey handling in `build_paper_rag_session()`.
- [x] 2.2 Preserve explicit `plan_worker` injection precedence over the environment flag.
- [x] 2.3 Add factory tests for default disabled, false disabled, true enabled, and explicit worker precedence.

## 3. Validation

- [x] 3.1 Run targeted adapter and factory tests.
- [x] 3.2 Run compile, strict change validation, smoke, full tests, and strict all-change validation.
