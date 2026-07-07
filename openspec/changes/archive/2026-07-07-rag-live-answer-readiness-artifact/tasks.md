## 1. Readiness Helper

- [x] 1.1 Add a deterministic live answer readiness helper that writes JSON and Markdown artifacts.
- [x] 1.2 Expose the helper through a CLI module and `scripts.dev check-live-answer-readiness`.

## 2. Workflow

- [x] 2.1 Update `rag-live-answer-eval.yml` to write readiness artifacts before skip/run decisions.
- [x] 2.2 Upload readiness artifacts even when LLM secrets are missing.

## 3. Tests And Verification

- [x] 3.1 Add unit tests for missing-secret and real-corpus readiness payloads.
- [x] 3.2 Update workflow/dev command contract tests.
- [x] 3.3 Run focused tests, compile, smoke, and OpenSpec validation.
- [x] 3.4 Commit the completed change.
