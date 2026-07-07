## Why

Real-corpus live answer evaluation requires `.newsroom/papers/<paper_id>/research_document.json` for every paper id referenced by `data/eval/golden_set.json`. Readiness now detects missing artifacts, but operators still need a reproducible command that repairs those missing artifacts without shrinking the golden set.

## What Changes

- Add a golden-set-driven paper ingest helper that selects missing paper ids from a golden set.
- Reuse the existing arXiv benchmark ingest path to fetch and parse selected papers.
- Expose the helper through a CLI module and `scripts.dev ingest-golden-set-papers`.
- Write a manifest describing selected ids and ingest outcomes.

## Impact

- Affected code: `business/research/rag/evaluation`, `business/research/rag/cli`, `scripts/dev.py`.
- Affected tests: golden-set ingest helper tests and dev command contract tests.
