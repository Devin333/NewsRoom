## Context

`rag-worker-planner-wiring` added the framework planner hook, the Research adapter, and optional `PaperRAGSession(plan_worker=...)` wiring. The production composition root still leaves `plan_worker=None`, so `rag_ask(gated=True)` cannot use the worker planner unless a caller injects one manually.

The RAG architecture guardrail remains unchanged: Harness owns routing, verification, retry budgets, and pass/fail decisions. The LLM worker may only emit a candidate `RetrievalPlanCandidate` payload that deterministic gates can accept or reject.

## Goals / Non-Goals

**Goals:**
- Add a real `ResearchCandidateWorkerPort` implementation that asks an LLM for a JSON retrieval plan candidate.
- Enable that worker only when `NEWS_RAG_LLM_PLANNER` is truthy.
- Preserve deterministic planning by default.
- Preserve explicit dependency injection: if a caller passes `plan_worker`, the environment flag MUST NOT replace it.
- Keep plan generation bounded and schema-oriented enough that invalid LLM output falls back through the existing worker failure path.

**Non-Goals:**
- Benchmark planner quality or tune prompts.
- Let the LLM make workflow, quality, memory, authorization, or publication decisions.
- Add new public API fields or CLI flags.
- Change answer generation or answer gate behavior.

## Decisions

1. Add `LLMResearchRAGPlanCandidateWorker` under `business/research/rag/adapters/`.

   This keeps the implementation behind `ResearchCandidateWorkerPort` and avoids importing infrastructure into business. The worker receives an async LLM callable, renders a concise prompt from the Harness planner request, parses JSON, and returns `{"candidate": ...}` on success.

2. Put environment discovery in `interfaces/services/paper_rag_factory.py`.

   The factory already composes rerankers, answer workers, and storage adapters from environment. It is the correct layer to read `NEWS_RAG_LLM_PLANNER` and call `build_unity_llm_call(max_tokens=...)`.

3. Treat invalid LLM output as worker failure.

   `ResearchRAGPlanWorker` converts adapter failures into `HarnessWorkerResult(status=FAILED)`, and `WorkerRAGPlanner` already falls back to `DeterministicRAGPlanner`. The new LLM-backed worker should raise or return a failed payload when JSON cannot be parsed into an object.

4. Keep the initial round deterministic.

   Existing `PaperRAGSession` uses `WorkerRAGPlanner(..., min_round_index=1)`. The new factory wiring reuses that behavior so LLM planner calls happen only on replans.

## Risks / Trade-offs

- LLM output can be malformed or low quality -> parse strictly and rely on existing deterministic fallback plus plan gates.
- Enabling the planner can add latency on replans -> keep it opt-in via `NEWS_RAG_LLM_PLANNER`.
- A model could include forbidden fields -> keep forbidden field reminders in prompt and rely on `RetrievalPlanCandidate` validation to reject flow-control fields.

## Migration Plan

1. Deploy with `NEWS_RAG_LLM_PLANNER` unset or false; behavior remains deterministic.
2. Enable in a controlled environment by setting `NEWS_RAG_LLM_PLANNER=1`.
3. Roll back by unsetting or setting the flag to false.
