## 1. Readiness Gate

- [x] 1.1 Add fixture and real-corpus eligibility gate flags to the readiness CLI.
- [x] 1.2 Forward gate flags through `scripts.dev check-live-answer-readiness`.

## 2. Workflow

- [x] 2.1 Update `rag-live-answer-eval.yml` to gate real-corpus eval with `--require-real-corpus`.
- [x] 2.2 Keep readiness artifact upload independent of eval execution.

## 3. Tests And Verification

- [x] 3.1 Add CLI tests for diagnostic zero-exit and real-corpus gate non-zero behavior.
- [x] 3.2 Update workflow/dev command contract tests.
- [x] 3.3 Run focused tests, compile, smoke, and OpenSpec validation.
- [x] 3.4 Commit the completed change.
