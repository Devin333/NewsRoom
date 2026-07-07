## Context

The generation phase can run a supplemental retrieval round when the answer gate finds unsupported claims and another generation attempt remains. The current implementation calls `_can_replan()` and consumes `rounds=1, replans=1`, so supplemental repair is coupled to the main retrieval loop rather than to generation repair policy.

## Goals / Non-Goals

**Goals:**
- Bound supplemental answer repair with `generation_policy.max_supplemental_rounds`.
- Let supplemental repair run even when main retrieval `rounds` or `replans` are exhausted.
- Continue enforcing query, source-read, memory-hit, context, and worker-call budgets through deterministic gates.
- Record stable skip reason codes in transcript events and metrics.

**Non-Goals:**
- Changing answer gate pass/fail criteria.
- Allowing unlimited supplemental retrieval.
- Changing main retrieval replan semantics.
- Changing LLM worker prompts or answer shape.

## Decisions

1. Add policy-level `max_supplemental_rounds`.
   - Rationale: supplemental repair belongs to generation policy, not main retrieval replan policy.
   - Default: one supplemental round is allowed when generation is enabled, preserving current successful retry behavior.
   - Alternative: raise `RAGBudget.max_rounds` and `max_replans` in Paper RAG factory. Rejected because it still couples repair behavior to main retrieval budget consumption.

2. Do not increment `rounds_used` or `replans_used` for supplemental repair.
   - Rationale: those counters represent the main PLAN -> EXECUTE -> VERIFY retrieval loop. Supplemental answer repair has its own count and is already bounded by generation attempts plus `max_supplemental_rounds`.
   - Alternative: add new fields to `RAGBudgetSnapshot`. Rejected for this change because transcript events and metrics can count supplemental rounds without changing the core budget snapshot contract.

3. Keep deterministic global budget checks for planned and executed supplemental work.
   - Rationale: independent supplemental rounds must still be bounded by query, source-read, memory-hit, context, and worker-call budgets to prevent runaway execution.

4. Add `reason_code` to skipped supplemental events and expose aggregated skip reasons in metrics.
   - Rationale: operators need to distinguish explicit supplemental-budget exhaustion from other gate failures without parsing free-form text.

## Risks / Trade-offs

- [Risk] Existing callers may assume `rounds_used` includes supplemental repair. -> Mitigation: existing supplemental metrics remain and become the authoritative repair counters.
- [Risk] Defaulting to one supplemental round can change behavior when `max_rounds=1` and `max_replans=0`. -> Mitigation: callers can set `max_supplemental_rounds=0` to disable repair explicitly, and tests cover both paths.
- [Risk] Query budget can still prevent repair after a large main retrieval plan. -> Mitigation: skip/failure events include structured budget gate details when deterministic gates reject supplemental work.
