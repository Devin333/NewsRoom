## Context

The bounded RAG loop already has deterministic plan gates and a `WorkerRAGPlanner` implementation. The missing piece is safe production wiring. Worker-generated plans must not decide routing, pass/fail, memory writes, or publication; they only produce `RetrievalPlanCandidate` payloads that deterministic gates validate.

## Goals / Non-Goals

**Goals:**
- Keep deterministic planning as the default.
- Enable worker planning only when a Research worker is explicitly injected.
- Start worker planning from round 2 by default (`min_round_index=1`) to keep the initial query cheap and stable.
- Pass executed query history and gap/rejection context into worker requests.
- Adapt `ResearchCandidateWorkerPort` without importing business code into framework.

**Non-Goals:**
- Build a real OpenAI worker implementation.
- Tune worker prompts or benchmark planner quality.
- Let the worker choose workflow decisions or bypass plan gates.
- Change `rag_ask` generation behavior.

## Decisions

1. Extend planner signatures with `executed_queries`.

   The new keyword argument defaults to `()`, so existing callers remain compatible. `BoundedRAGSessionController` passes its normalized query history, letting worker candidates avoid repeats while query-dedup gate remains the final guard.

2. Add `min_round_index` to `WorkerRAGPlanner`.

   Round 0 falls back to deterministic planning. From round 1 onward, the worker can propose a candidate. If the worker fails or omits a candidate, deterministic fallback is used.

3. Add `ResearchRAGPlanWorker` in business adapters.

   It calls `ResearchCandidateWorkerPort.generate_candidate(task="rag_plan_candidate", payload=request)` and returns `HarnessWorkerResult`. This keeps the framework worker shape isolated from Research's worker port.

4. Wire through `PaperRAGSession`.

   `PaperRAGSession(plan_worker=...)` constructs `WorkerRAGPlanner(ResearchRAGPlanWorker(plan_worker), min_round_index=1)`. If no worker is supplied, no planner is passed and controller behavior remains deterministic.

## Risks / Trade-offs

- Worker plan quality may be poor. Plan gates and deterministic fallback prevent unsafe execution; planner effectiveness can be measured later.
- Adding executed query history changes the worker request payload. The payload is additive and does not affect deterministic planner behavior.
- The interface factory cannot discover a production worker yet. It exposes a parameter for callers/tests; environment-based construction can be added once a real worker exists.
