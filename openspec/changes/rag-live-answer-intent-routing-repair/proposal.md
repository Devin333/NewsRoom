## Why

The real-corpus live answer eval now passes abstention thresholds, but its remaining answerable-case failures are concentrated in retrieval/context coverage. Failure details show evaluation, experiment, appendix, benchmark, dataset split, user-study, prompt, and win-rate questions being classified as plain `concept_method`, which routes them only through `method_body` instead of result and table context.

## What Changes

- Expand Paper-specific query intent signals so live-answer result/evaluation questions route to result-aware retrieval plans.
- Preserve explicit figure, table, formula, citation, contribution, comparison, and method semantics.
- Add regression tests using real questions from the live answer failure details.
- Document the current live-answer routing repair target in the July baseline notes.

## Capabilities

### New Capabilities

### Modified Capabilities
- `rag-kernel-query-intent`: Paper Research routing must classify evaluation/result-oriented natural questions as result-aware intents instead of the fallback method route.

## Impact

- Affected routing code: `business/research/rag/retrieval/paper_policy.py`.
- Affected tests: `tests/business/research/rag/test_routing.py`.
- Affected review notes: `docs/reviews/live-answer-baseline-2026-07.md`.
