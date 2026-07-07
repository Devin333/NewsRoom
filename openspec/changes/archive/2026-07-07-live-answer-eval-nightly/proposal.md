## Why

The current PR evidence gate evaluates answer metrics with deterministic synthetic answer samples. That protects metric calculation regressions, but it does not exercise the gated answer generation path or clearly label the metric as pipeline-only.

## What Changes

- Add a `--live-answer-eval` mode to `run_evidence_eval` that evaluates generated answers from the gated Harness answer path.
- Record `answer_eval_mode` in evidence report metadata.
- Keep deterministic answer evaluation available for PR gates, but rename promotion checks so reports make the deterministic scope clear.
- Add tests that exercise live answer sample conversion with a fake gated service.

## Capabilities

### New Capabilities
- `rag-live-answer-evaluation`: Evidence evaluation can run answer metrics against gated Harness-generated answer payloads.

### Modified Capabilities

## Impact

- Affects `business/research/rag/cli/run_evidence_eval.py`, CI promotion checklist labels, and RAG evaluation tests.
- No external model is required for PR tests; production/nightly live mode uses the configured answer worker path.
