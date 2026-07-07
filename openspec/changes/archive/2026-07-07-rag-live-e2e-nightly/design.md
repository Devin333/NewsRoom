## Design

The workflow is deliberately separate from `.github/workflows/ci.yml`.

- Triggered by `workflow_dispatch` and a weekly cron schedule.
- Runs on Ubuntu with Python 3.11.
- Starts Postgres and Qdrant service containers.
- Sets `NEWS_RUN_LIVE_RESEARCH_E2E=1`, `NEWS_QDRANT_URL`, and `NEWS_DATABASE_DSN`.
- Runs `python -m scripts.dev test-rag-live-e2e`, which dispatches the existing `tests/business/research/integration/test_chunk_paper_e2e.py`.

The existing test remains opt-in locally. Without the live E2E environment variables it skips, so developer machines and ordinary CI runs do not need network, Qdrant, or Postgres.

## Non-Goals

- Do not make live arXiv/Qdrant/Postgres E2E a PR blocking check.
- Do not add LLM, reranker model download, or external credential requirements.
- Do not replace deterministic PR CI eval gates.
- Do not store live E2E artifacts as release benchmarks yet.
