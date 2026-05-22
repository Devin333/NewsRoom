## Context

Business full productization and runtime acceptance already exist. This change completes the final business runtime acceptance surface by extending the current service and CLI, not by adding a parallel runtime path.

## Goals / Non-Goals

**Goals:**

- Verify final business run public surfaces, artifacts, cross-board graph intelligence, weekly outputs, proposal persistence, and eval suite readiness.
- Keep all checks offline and deterministic.
- Ensure final public surfaces do not expose raw or secret-like field names.

**Non-Goals:**

- No framework runtime refactor.
- No productized board runtime rewrite.
- No real network, LLM, notification, or automatic proposal application.

## Decisions

- Reuse the existing `BusinessAcceptanceService` and add `run_final_business_acceptance` so CLI and service entrypoints stay singular.
- Move final runtime fixture helpers to `business/boards/final_runtime_fixtures.py` and keep test imports compatible through a re-export module.
- Treat final business artifacts as artifact-ref contracts; do not force file persistence where final runtime does not currently publish files.
- Apply raw-field filtering only to final public evidence-derived payload construction and tests, leaving lower-layer source raw artifact tests intact.

## Risks / Trade-offs

- Final acceptance smoke can be slower than a simple unit test; mitigation is to use small offline fixtures.
- Exact forbidden-field scanning can catch intentional metadata names; mitigation is to scope the strict scan to final business public surfaces.
