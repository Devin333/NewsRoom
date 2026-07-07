## 1. Live Eval Inputs

- [x] 1.1 Add external `golden_set_path` and `papers_dir` support to `run_live_answer_eval`.
- [x] 1.2 Add CLI options for `--golden-set` and `--papers-dir`.
- [x] 1.3 Preserve fixture-backed default mode.

## 2. Workflow And Tests

- [x] 2.1 Add tests proving external golden set mode bypasses fixture generation and records the external paths.
- [x] 2.2 Update the live answer eval workflow with a real-corpus step that skips clearly when `.newsroom/papers` is absent.
- [x] 2.3 Update workflow/CLI contract tests for the new real-corpus step and CLI options.

## 3. Verification

- [x] 3.1 Run focused live answer eval and workflow tests.
- [x] 3.2 Run compile and `openspec validate rag-live-real-golden-set-eval --strict`.
- [x] 3.3 Commit the completed change.
