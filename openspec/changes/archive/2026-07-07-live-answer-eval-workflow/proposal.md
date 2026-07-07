## Why

`--live-answer-eval` can evaluate generated answers from the gated Harness path, but no dev command or scheduled workflow invokes it. That leaves real-model abstention drift invisible after the CLI capability lands.

## What Changes

- Add a `scripts.dev run-live-answer-eval` command that prepares fixture papers and runs `run_evidence_eval --live-answer-eval`.
- Add a scheduled and manually dispatchable GitHub Actions workflow for live answer evaluation.
- Pass OpenAI-compatible LLM secrets into the workflow and skip the live step clearly when required secrets are absent.
- Upload live answer evidence reports as workflow artifacts.
- Add contract tests for the dev command and workflow wiring.

## Capabilities

### New Capabilities
- `rag-live-answer-eval-workflow`: Nightly/manual automation runs live generated-answer evidence evaluation and preserves reports.

### Modified Capabilities

## Impact

- Affects `scripts/dev.py`, a new RAG live answer eval CLI module, GitHub Actions workflow configuration, and contract/business tests.
- Requires `OPENAI_BASE_URL` and `OPENAI_API_KEY` secrets for the workflow to execute the live LLM path.
- Does not change PR deterministic eval thresholds or production RAG behavior.
