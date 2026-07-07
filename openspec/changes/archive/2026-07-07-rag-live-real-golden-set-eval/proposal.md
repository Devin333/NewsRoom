## Why

Live answer evaluation is scheduled and can run the gated Harness answer path, but the helper always builds a small fixture golden set. That leaves the curated repository golden set, including real abstain samples, outside the live answer evaluation path.

## What Changes

- Allow `run_live_answer_eval` and its CLI to accept an external `--golden-set` and `--papers-dir`.
- Preserve the current fixture-backed default mode for CI-friendly smoke coverage.
- When external inputs are provided, pass the golden set directly to `run_evidence_eval --live-answer-eval` without rebuilding it from fixtures.
- Add workflow coverage for the real-corpus mode with a graceful skip when parsed paper artifacts are unavailable.
- Add tests proving external golden sets bypass fixture golden-set generation.

## Capabilities

### New Capabilities
- `rag-live-real-golden-set-eval`: Live answer evaluation can consume the repository real-corpus golden set with caller-provided parsed paper artifacts.

### Modified Capabilities

## Impact

- Affected code: `business/research/rag/evaluation/live_answer_eval.py`, `business/research/rag/cli/run_live_answer_eval.py`, `scripts/dev.py`.
- Affected workflow: `.github/workflows/rag-live-answer-eval.yml`.
- Affected tests: live answer eval unit tests and workflow/CLI contract tests.
- No breaking change; default `python -m scripts.dev run-live-answer-eval` remains fixture-backed.
