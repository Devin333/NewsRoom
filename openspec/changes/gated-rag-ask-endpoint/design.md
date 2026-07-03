## Context

T4 added a framework generation phase and a Research `PaperAnswerWorker`, but the production-facing chunk RAG ask path still uses `ResearchRetriever` plus `AnswerGenerator` directly. This change connects the ask surface to `PaperRAGSession` only when generation is explicitly requested through the gated path.

## Goals / Non-Goals

**Goals:**
- Make `rag_ask(generate=True)` use `PaperRAGSession` with `generation_policy.enabled`.
- Return explicit `answered`, `abstained`, `insufficient_evidence`, or `halted` status.
- Expose answer claims, cited evidence ids, gate results, transcript id, and context pack summary.
- Preserve the retrieve-only payload for `generate=False`.
- Preserve a `gated=False` fallback for the old direct generator path.

**Non-Goals:**
- Remove the legacy direct generator path.
- Add unsupported-claim supplemental retrieval.
- Change answer gate semantics.
- Add new LLM judge or answer faithfulness scoring.

## Decisions

1. `PaperRAGSession` accepts an optional `answer_worker` and `generation_policy`.

   The session remains the owner of harness execution. The factory builds `PaperAnswerWorker(AnswerGenerator(...))` only when requested, avoiding LLM construction for retrieve-only calls.

2. `AskPaperUseCase` builds a goal instead of accepting a fully formed goal only.

   It maps query intent into required evidence types and allowed source refs. This keeps endpoint/service code thin and gives tests a deterministic business-level target.

3. `PaperRagApplicationService.rag_ask` keeps `generate=False` unchanged.

   Retrieval-only consumers keep seeing `paper_id`, `question`, `intent`, `passages`, and `metrics`. Gated fields are added only for generated calls.

4. The API gets a `gated` request flag defaulting to true.

   This makes the safer path the default for generated answers, while allowing explicit fallback during rollout.

## Risks / Trade-offs

- Gated generation may abstain where the old path returned text -> This is intentional and exposes unsupported answer generation instead of hiding it.
- The first gated answer may be slower because it initializes the LLM call and resident reranker -> Retrieve-only calls still avoid answer worker construction.
- Goal intent mapping may be imperfect -> It is deterministic, testable, and can be tuned without changing the framework loop.
