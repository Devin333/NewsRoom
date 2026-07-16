# Deterministic Replay And Recorded Activity Evidence

Date: 2026-07-16

OpenSpec tasks: 6.1-6.5

## Implemented contracts

- `REBUILD_STATE` and `VERIFY_HISTORY` execute through the deterministic replay engine. Authorized `REDELIVER` delegates to the separately authorized delivery operation and cannot be selected as generic replay-to-bus behavior.
- Replay captures a finite source high watermark, validates ordered canonical history, schema and checksums, applies registered pure upcasters and reducers, persists progress/checkpoints/reports, and resumes after the last committed sequence without mutating source history.
- Nondeterministic LLM, Tool, MCP, HTTP, retrieval, memory write, publication, email, clock, random, and external database activity kinds use one versioned recorded-activity contract. Input, output or error, and record bytes have independent encrypted references.
- Harness persists accepted input before invoking a worker. A committed terminal record is resolved without reinvoking the provider and is checked against the event reference, deterministic history, descriptor, tenant, classification, versions, status, and error class.
- PostgreSQL and SQLite implement exact retry, pending-to-terminal compare-and-set, tenant isolation, ciphertext-only storage, integrity-bound reference validation, and audited access.

## Failure evidence

- Replay tests cover interruption/resume, checkpoint corruption, unsorted/noncontiguous history, unknown schema, upcaster failure, missing/corrupt activity, command nondeterminism, concurrent live append above the captured watermark, poison-event redelivery, and report/checkpoint store failures.
- Harness tests prove terminal `failed`, `blocked`, and `waiting_approval` outcomes recover without a second provider call and reject missing payloads plus descriptor, reference, status, error-class, and history-binding tampering.
- PostgreSQL tests run against PostgreSQL 18.3 in the isolated `newsroom_event_test` database and exercise real transactions and concurrent exact retries.

## Verification results

```text
framework activity/replay plus SQLite activity store: 117 passed
Harness suite plus SQLite durable integration: 299 passed
generic activity plus Harness contract subset: 126 passed
PostgreSQL recorded activity integration: 9 passed
PostgreSQL/SQLite event-store conformance from a clean test database: 52 passed
targeted subprocess import/crash regressions after trace-WIP isolation: 4 passed
git diff --check: passed
```

The final repository-wide compile, smoke, all-strict validation, fault suite, and benchmark remain tracked by tasks 10.1-10.5.
