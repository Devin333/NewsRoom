## 1. Evaluation evidence model

- [x] 1.1 Add immutable corpus, observation, thresholds, metric, report, and gate result models.
- [x] 1.2 Replay observed responses through the canonical compiler/strict decoder/local validator.
- [x] 1.3 Gate every schema, Research quality, rejection, latency, token, and cost metric independently from its baseline.
- [x] 1.4 Add stable corpus, observation, report, and release digests.

## 2. Release and rollout policy

- [x] 2.1 Add immutable Harness-owned release records with approval, scope, evidence, rollout revision, and rollback policy.
- [x] 2.2 Require an approved enabled record for native strict/constrained projection.
- [x] 2.3 Implement disabled and shadow behavior without weakening local validation or silently enabling provider enforcement.
- [x] 2.4 Parse and validate versioned release records from model configuration.

## 3. Corpora and repeatable evaluation

- [x] 3.1 Add a NewsRoom-authored JSONSchemaBench-taxonomy-derived capability corpus with pinned provenance and license disposition.
- [x] 3.2 Add held-out Research observations for answer quality, grounding, citation, latency, tokens, and cost.
- [x] 3.3 Add a replay CLI and approved recorded-provider evaluation/release evidence.
- [x] 3.4 Add a held disabled DashScope rollout record without claiming uncollected live evidence.

## 4. Verification

- [x] 4.1 Add evaluator pass/fail, anti-compensation, digest tamper, approval, shadow, scope, rollback, and config tests.
- [x] 4.2 Update existing provider tests to use explicit approved release fixtures for native/constrained modes.
- [x] 4.3 Run focused suites, compile, smoke, strict OpenSpec validation, diff/secret checks, archive, and commit.
