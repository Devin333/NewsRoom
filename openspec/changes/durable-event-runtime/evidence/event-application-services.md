# Event Application Services Evidence

Date: 2026-07-16

OpenSpec tasks: 8.1 and 8.4

## Implemented contracts

- Application-owned reader, projection, replay, delivery-operations, and quarantine services depend on framework ports rather than concrete storage, dispatchers, executors, or replay runtime implementations.
- Authorization requests and decisions are checksum-bound to the authenticated principal, tenant, exact operation target, and bounded evidence references. Caller context cannot self-assert permissions.
- Durable reads preserve tenant scope, fixed high watermarks, strictly advancing sequence cursors, event/schema filters, and canonical step context. Invalid or non-advancing store pages fail closed.
- Projection rebuild derives `events.jsonl` only below the configured artifact root, pins the requested durable high watermark, uses the deterministic redacted exporter, and never publishes or feeds exported rows into the live runtime.
- Projection status verifies manifest metadata, file bytes, checksum, count, and the durable stream prefix before reporting `current`, `running`, or `stale`; missing, partial, corrupt, or ahead-of-store projections are typed conflicts.
- Replay checkpoints, redelivery selections, dead-letter operations, quarantine dispositions, and list/get results are validated against the exact authorized identity, filters, subscription, and tenant before mutation or return.

## Adversarial coverage

- Cross-tenant dead-letter requeue and redelivery are rejected before runtime mutation.
- Replay authorization binds checkpoint ID, checksum, mode, stream, tenant, sequence, and source high watermark.
- Same-tenant wrong-ID and filter-violating store responses are rejected.
- Step filtering scans durable pages without missing matches and rejects repeated or non-advancing cursors.
- Projection path override, traversal, missing/corrupt bytes, partial metadata, concurrent append, and unavailable-store cases fail safely.

## Verification results

```text
event application service tests: 34 passed
independent re-review: PASS, no remaining P1/P2 findings
python -m scripts.dev compile: passed
git diff --check (scoped files): passed
```

Transport cutover, availability response mapping, and operator API/CLI/MCP surfaces remain tracked by tasks 8.2, 8.3, and 8.5.
