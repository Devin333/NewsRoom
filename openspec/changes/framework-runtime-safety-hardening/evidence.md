# Verification Evidence

Verified on 2026-08-04 from `F:\github\NewsRoom` with the repository virtual environment.

## Contract And Regression Coverage

- Changed-test sweep: `754 passed, 10 skipped` across 56 modified or newly added test files.
- Focused Tool, Workflow, Redis lease, worker, API, MCP, stdio, and registry sweep: `89 passed`.
- Deterministic concurrency and fault-injection repetition: three consecutive runs of `22 passed`.
- Memory regressions found by the full suite were root-cause fixed; the focused memory sweep passed with `25 passed`.
- Full pytest suite after fixes: `5984 passed, 100 skipped, 24 deselected`.
- The optional real Redis lease test remains environment-gated because `NEWS_TEST_REDIS_URL` was not configured; deterministic fake-Redis script conformance passed.

## Delivery Gates

- `openspec validate framework-runtime-safety-hardening --strict`: passed.
- `openspec validate --all --strict`: `513 passed, 0 failed`.
- `git diff --check`: passed before final delivery checks.
- `python -m scripts.dev compile`: passed before the full-suite run.
- `python -m scripts.dev smoke`: final pre-commit run passed with `1962 passed, 23 deselected`.
- `python -m scripts.dev export-openapi`: completed successfully and refreshed `docs/api/openapi.json` from the live application.

## Scope Audit

- No files under `openspec/changes/durable-event-runtime` were modified.
- Local `.hex-skills/runtime-artifacts` output is excluded through `.gitignore` and is not part of the delivery.
- The existing `framework.agent.artifacts` callers and architecture test require the package relocation; the moved package contains the same artifact implementation with normalized imports.
