## Why

The enterprise RAG review found that `ResearchRAGPlanWorker` exists but the production paper RAG factory still passes `plan_worker=None` by default. As a result, verified replans in the `rag_ask` production path remain deterministic even when an LLM planner has been explicitly enabled for candidate query generation.

## What Changes

- Add a production `ResearchCandidateWorkerPort` implementation for RAG plan candidates backed by the existing Unity/OpenAI-compatible LLM callable.
- Wire `build_paper_rag_session()` to construct the planner worker when `NEWS_RAG_LLM_PLANNER` is enabled.
- Keep deterministic planning as the default when the environment flag is absent, false, or an explicit `plan_worker` is provided.
- Add factory and adapter tests proving opt-in construction, explicit injection precedence, and safe deterministic default behavior.

## Capabilities

### New Capabilities
- `wire-llm-planner-default`: Environment-controlled production wiring for the Paper RAG LLM planner worker.

### Modified Capabilities

## Impact

- Affected interface composition: `interfaces/services/paper_rag_factory.py`.
- Affected Research adapters: `business/research/rag/adapters/`.
- Affected tests: Paper RAG factory and Research RAG plan worker tests.
- No public API or schema changes.
