## Why

The Graph artifact path now has verified materialization, deduplication, run-bounded quota, catalog references, and deterministic dry-run GC planning, but it cannot safely execute a deletion or explain storage cost across tenants, runs, nodes, and artifact classes. The next PRD gate requires lifecycle authority and durable cost facts before shadow evidence or legacy-writer removal can be trusted.

## What Changes

- Add a controlled two-step Graph artifact GC workflow that snapshots catalog claims and references, persists an immutable plan, verifies that the plan is still current, deletes only verified eligible bytes, and finalizes catalog lifecycle state idempotently.
- Add explicit reference-release and claim-retirement operations so expired ownership can be removed by Harness-controlled lifecycle policy without leaving dangling claims, references, or canonical entries.
- Extend quota configuration and the existing SQLite result ledger with exactly-once tenant, run, and artifact-class byte/count reservation, settlement, usage, and crash reconciliation.
- Persist sanitized, idempotent usage observations for materialization, cache access, artifact read-back, context loading, GC, and failed writes; raw artifact or prompt content is never recorded.
- Generate deterministic daily cost reports with logical bytes, unique physical bytes, dedup ratio, cache hit ratio, expired bytes, failed writes, and context-load bytes, grouped by tenant, run, graph node, artifact class, and policy version.
- Generate durable threshold alerts for run/tenant quota pressure, GC backlog, read-back failures, catalog drift, and cache stampede, with stable identities and acknowledgement-safe replay.
- Add production composition and operator interfaces for GC plan/apply, cost reports, and alerts using the existing catalog, filesystem artifact store, and SQLite result database; no fake or in-memory production fallback is allowed.
- Preserve `legacy`, `shadow`, `enforce`, and `read_only` routing semantics and all report/publication authority. This change does not delete the legacy Workflow writer or change Research quality routing.

## Capabilities

### New Capabilities

- `graph-artifact-gc-execution`: Controlled reference retirement, immutable GC plans, idempotent physical deletion, catalog finalization, recovery, and reconciliation.
- `graph-artifact-cost-governance`: Durable usage facts, multidimensional quota accounting, deterministic daily cost reports, threshold alerts, and operator queries.

### Modified Capabilities

- `graph-artifact-result-contract`: Add bounded tenant and artifact-class quota limits plus governance thresholds to the immutable versioned configuration.
- `graph-artifact-catalog-dedup`: Add lifecycle-safe claim/reference retirement, plan snapshot evidence, and tombstoned deletion finalization without weakening dedup or reconciliation.
- `graph-result-materializer`: Make quota reservation class-aware and durably record exactly-once materialization/cache/read-back usage outcomes.
- `graph-artifact-context-loading`: Record actual approved context-load bytes/tokens as idempotent sanitized usage facts.
- `research-production-composition`: Explicitly compose the real governance ledger, GC adapter, reporter, and alert evaluator from the production settings snapshot.

## Impact

- Affected framework contracts: `framework/harness/artifacts`, `framework/harness/runtime/result_policy.py`, `framework/harness/runtime/materializer.py`, and artifact context loading contracts.
- Affected infrastructure adapters: `LocalJsonArtifactCatalog`, `SQLiteGraphResultStore`, and the Research filesystem artifact adapter. The existing physical artifact store remains canonical.
- Affected interfaces: Research settings/composition and operator-facing storage commands/services for plan, apply, report, and alert inspection.
- Existing SQLite and Local JSON formats require explicit versioned migrations with restart, tamper, concurrency, and rollback-readable tests.
- No new external SDK or network service is required; local production remains file-backed and deterministic.
