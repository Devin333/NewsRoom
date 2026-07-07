## Why

The enterprise RAG review still lists real-data end-to-end coverage as a release-readiness gap. The repository already has an opt-in live Paper RAG integration test that ingests a real arXiv paper, writes chunks to Qdrant and Postgres, and verifies retrieval, but there is no CI workflow that runs it regularly.

## What Changes

- Add a scheduled and manually-triggered GitHub Actions workflow for the live Paper RAG E2E.
- Start real Postgres and Qdrant service containers in the workflow.
- Expose the live E2E through `python -m scripts.dev test-rag-live-e2e`.
- Keep normal push and PR CI offline and deterministic.
- Add contract tests for the workflow and dev command registration.

## Impact

- Affected CI: new `.github/workflows/rag-live-e2e.yml`.
- Affected developer tooling: `scripts/dev.py`.
- Affected tests: workflow contract and interface command registration.
- Uses public arXiv network access only in the scheduled/manual live workflow, not in PR CI.
