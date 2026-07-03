## Why

The enterprise RAG review calls out that abstention accuracy is still unverified by the CI path. The existing Paper RAG CI gate exercises retrieval and promotion checks, but its generated golden set excludes negative QA samples and therefore cannot regress expected-abstain behavior or answer-level success metrics.

## What Changes

- Keep deterministic negative QA pairs in the CI mini corpus.
- Add a no-network deterministic answer evaluation mode to the evidence eval CLI.
- Enforce answer abstention accuracy and answer success thresholds in the CI gate.
- Add promotion checks proving expected-abstain samples are present and answer metrics meet PR gates.

## Impact

- Affected eval CLI: `business/research/rag/cli/run_evidence_eval.py`.
- Affected CI gate: `business/research/rag/evaluation/ci_eval_gate.py`.
- Affected tests: Paper RAG CI gate and answer/evaluation report tests.
- No external service, LLM, database, vector store, public API, or production schema changes.
