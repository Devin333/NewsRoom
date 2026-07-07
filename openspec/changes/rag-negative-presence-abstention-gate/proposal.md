## Why

Real-corpus live answer evaluation still exposed expected-abstain questions where the model returned unrelated paper context instead of refusing the unsupported request. Existing phrase markers catch explicit context-absence answers, but they do not catch non-abstention recitations that never address the queried out-of-domain subject.

## What Changes

- Add deterministic runtime normalization for negative presence questions such as "Does this paper include/specify/report/discuss/provide ...?" when the generated answer has very low lexical overlap with the requested target.
- Record the normalization reason and extracted target terms in answer worker metadata.
- Add regression tests for the commercial smartphone launch-date failure and guardrails showing legitimate supported yes/no answers are not forced to abstain.

## Capabilities

### New Capabilities

### Modified Capabilities
- `rag-live-answer-evaluation`: live answer generation and evaluation treat unrelated recitations for negative presence questions as abstentions.

## Impact

- Affected runtime code: `business/research/rag/adapters/answer_worker.py`.
- Affected tests: `tests/business/research/rag/adapters/test_answer_worker.py`.
- Affected documentation: `docs/reviews/live-answer-baseline-2026-07.md`.
