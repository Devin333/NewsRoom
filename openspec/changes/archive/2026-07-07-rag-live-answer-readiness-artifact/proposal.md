## Why

The live answer eval workflow can now run fixture and real-corpus evaluations, but when credentials or parsed paper artifacts are missing the evidence is only an Actions log line. The PRD's remaining production-readiness gap needs a durable artifact that explains whether the run produced a real baseline or why it was skipped.

## What Changes

- Add a no-network readiness helper for Paper RAG live answer evaluation.
- Record LLM secret presence without exposing secret values.
- Record real golden set and parsed paper corpus availability.
- Write JSON and Markdown readiness artifacts before the workflow decides whether to run or skip live evaluation.
- Upload readiness artifacts even when live answer eval is skipped.

## Capabilities

### New Capabilities
- `rag-live-answer-readiness-artifact`: Live answer eval runs produce durable readiness/skip artifacts that explain whether fixture and real-corpus evaluation can run.

### Modified Capabilities

## Impact

- Affected code: `business/research/rag/evaluation`, `business/research/rag/cli`, `scripts/dev.py`.
- Affected workflow: `.github/workflows/rag-live-answer-eval.yml`.
- Affected tests: live answer eval workflow contract and readiness unit tests.
- No network calls or LLM calls are added.
