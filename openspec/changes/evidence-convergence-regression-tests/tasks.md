## 1. Evidence Convergence Regression

- [x] 1.1 Add business integration coverage for required experiment evidence with method-only returned evidence.
- [x] 1.2 Assert the result remains `INSUFFICIENT_EVIDENCE`, the gap report still lists `experiment`, and accepted evidence is content-typed as `method`.

## 2. Golden And Gated Abstention Regression

- [x] 2.1 Add a regression that loads legacy `data/eval/golden_set.json` rows with default `expected_behavior="answer"`.
- [x] 2.2 Add a gated service regression for an explicit `expected_behavior="abstain"` golden case.

## 3. Validation

- [x] 3.1 Run targeted integration, service, and evidence eval tests.
- [x] 3.2 Run compile, strict OpenSpec validation, smoke, full tests, and strict all-change validation.
