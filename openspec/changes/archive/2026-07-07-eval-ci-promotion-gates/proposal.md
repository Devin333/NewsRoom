## Why

The enterprise RAG review found that retrieval and promotion evaluation still do not run in CI, so production RAG regressions can merge without PR-level evidence metrics. This change adds a fast, deterministic gate that exercises the real Paper RAG retrieval/evidence evaluator and records promotion-threshold artifacts on every CI run.

## What Changes

- Add a PR-grade Paper RAG eval gate that builds a deterministic mini corpus, runs live in-memory retrieval evaluation, and enforces retrieval thresholds.
- Add a promotion gate artifact that summarizes retrieval metrics against staged promotion thresholds for CI review.
- Expose the gate through `python -m scripts.dev test-rag-eval-gate`.
- Run the gate from `.github/workflows/ci.yml`.
- Add tests covering the gate reports, failure behavior, dev command registration, and CI wiring.

## Capabilities

### New Capabilities
- `eval-ci-promotion-gates`: Deterministic CI execution of Paper RAG retrieval metrics and promotion gate artifacts.

### Modified Capabilities

## Impact

- Affected CI: `.github/workflows/ci.yml`.
- Affected developer tooling: `scripts/dev.py`.
- Affected Research RAG eval code: `business/research/rag/evaluation/` and `business/research/rag/cli/`.
- Affected tests: RAG eval tests and dev/CI registration tests.
- No network, external service, public API, or persisted production schema changes.
