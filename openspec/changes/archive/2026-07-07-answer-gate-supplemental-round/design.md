## Context

The first gated generation slice intentionally made answer generation single-attempt: an answer worker drafts a candidate, deterministic answer gates verify it, and invalid answers produce `ABSTAINED`. The answer gate now exposes unsupported claims through `unsupported_claims_from_answer_gate`, and `RAGExecutionPolicy.max_generation_attempts` already exists, but the session controller does not use either value.

The controller must remain the workflow authority. The answer worker can only draft candidate text and claims; it must not decide whether to replan, retry, write memory, or bypass quality gates.

## Goals / Non-Goals

**Goals:**
- Consume `generation_policy.max_attempts` for bounded answer retries.
- Convert unsupported answer claims into a supplemental gap report entry.
- Reuse existing plan verification, retrieval execution, source verification, context-pack assembly, and replan budget for supplemental retrieval.
- Emit transcript events that make supplemental attempts reviewable.
- Keep single-attempt abstention behavior when max attempts is 1 or no controlled supplemental round can run.
- Set production paper answer sessions to two attempts.

**Non-Goals:**
- Add semantic LLM judging for unsupported claims.
- Change answer prompt construction or claim extraction.
- Add memory writes, skill evolution, or plan-worker default wiring.
- Add more than the configured bounded number of answer attempts.

## Decisions

1. Keep supplemental retrieval inside `BoundedRAGSessionController`.

   The controller already owns PLAN -> EXECUTE -> VERIFY and budget accounting. A helper method can reuse the same planner, gates, source verifier, and assembler without adding an answer-worker-driven route.

2. Spend existing replan budget for supplemental rounds.

   Unsupported-claim retrieval is a replan triggered by deterministic verification failure. It should consume `replans_used` and respect `max_replans` and `max_rounds`, matching the rest of the bounded loop.

3. Preserve `state.gap_report["unsupported_claims"]`.

   The planner already receives `gap_report`; adding unsupported claims there lets deterministic and worker planners see the same structured gap context. After supplemental source verification, the refreshed gap report retains the claims that caused the round for traceability.

4. Reassemble and verify a new context pack before retrying generation.

   New evidence must pass source gates and context-pack gates before the answer worker sees it. If no valid pack can be assembled, the controller abstains with the original answer-gate failure details.

## Risks / Trade-offs

- Supplemental retrieval can still return no useful evidence -> final answer remains `ABSTAINED`, with the failed gate details preserved.
- Spending replan budget may reduce later retrieval flexibility -> this is intentional because answer-driven retrieval is still a controlled replan.
- Existing planners may not use unsupported claims richly yet -> the deterministic planner still receives the gap report, and future plan-worker improvements can consume the same field without changing the contract.
