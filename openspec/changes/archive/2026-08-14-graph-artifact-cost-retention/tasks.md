## 1. Governance Contracts And Configuration

- [x] 1.1 Extend `GraphArtifactPersistenceConfig` with bounded tenant/class quota and governance alert settings, exact serialization, environment parsing, and rollback-readable policy validation.
- [x] 1.2 Add backend-neutral exact-schema contracts for usage facts, catalog snapshots/detach receipts, lifecycle authorization/retirement, GC operations, cost reports, and alerts.
- [x] 1.3 Extend catalog, quota, usage, physical lifecycle, and governance ledger ports without importing filesystem, SQLite, Research business, interface, or vendor modules into `framework/harness`.
- [x] 1.4 Add contract/config/error/architecture tests for exact keys, deterministic checksums, bounds, sanitized failures, tenant scope, and dependency direction.

## 2. Durable Quota And Governance Ledger

- [x] 2.1 Add a transactional version-1-to-version-2 migration for `SQLiteGraphResultStore` that preserves existing attempt/envelope checksums and rejects partial or unsupported migration state.
- [x] 2.2 Implement exactly-once run, tenant, and tenant-plus-artifact-class byte/count reservation, settlement, snapshots, and evidence-based pending reconciliation in one SQLite transaction boundary.
- [x] 2.3 Implement idempotent sanitized usage facts for materialization, cache lookup/write/read-back, context load, catalog drift, and GC transitions with indexed UTC/dimension queries.
- [x] 2.4 Implement durable GC plan/operation/tombstone state, cost report revisions, alert records, and compare-and-set acknowledgement in the existing result database.
- [x] 2.5 Cover migration, restart, conflict, tamper, quota exhaustion, settlement/reconciliation, concurrent tenants/runs/classes, fact idempotency, and ledger integrity with infrastructure tests.

## 3. Catalog Lifecycle And Physical GC

- [x] 3.1 Add deterministic catalog snapshots and GC decision evidence containing entry, claim, reference, protection, snapshot, decision, and plan checksums.
- [x] 3.2 Add exact lifecycle-authorized reference retirement and atomic stale-safe catalog detach that removes one eligible entry plus inactive claims/references without partial state.
- [x] 3.3 Add a run-bound filesystem Graph artifact lifecycle adapter that verifies internal refs, updates manifest membership, quarantines on the same volume, purges idempotently, and rejects arbitrary/public/cross-run/tampered targets.
- [x] 3.4 Cover TTL boundaries, active run/report/evidence/replay protection, cross-run dedup, stale plans, concurrent executors, restart at every transition, symlink/reparse/path escape, and quarantine recovery.

## 4. Governance Runtime And Accounting Integration

- [x] 4.1 Make materializer quota reservations class/policy aware and commit exactly-once durable usage for inline, artifact, cache, omitted, recovered, and failed outcomes.
- [x] 4.2 Record approved context-load bytes/tokens through the durable usage port before returning context, including idempotent restart and typed ledger-failure behavior.
- [x] 4.3 Implement `GraphArtifactGovernanceRuntime` with bounded lifecycle release and `prepared -> catalog_detached -> quarantined -> purged -> completed` GC recovery semantics.
- [x] 4.4 Implement deterministic provisional/closed daily cost reports from catalog snapshot plus usage watermark, including multidimensional logical/unique bytes, dedup, cache, expiry, failure, context, and GC aggregates.
- [x] 4.5 Implement pure threshold alert evaluation plus durable idempotent alert delivery/acknowledgement for quota pressure, GC backlog, read-back failure, catalog drift, and cache stampede.
- [x] 4.6 Add framework/runtime tests for accounting atomicity, recovery, report reproducibility, late revisions, scoped unique bytes, nullable cache ratio, alert identity, and payload privacy.

## 5. Production Composition And Operator Surface

- [x] 5.1 Parse all new governance settings from the immutable Research environment snapshot and fail closed with sanitized typed unavailability for invalid values.
- [x] 5.2 Compose one real catalog, upgraded result/governance store, filesystem lifecycle adapter, usage-accounted materializer/context loader, and governance runtime in Research production; preserve explicit rollout-mode write restrictions and no fake fallback.
- [x] 5.3 Add application-service operations and `news storage graph-artifacts` commands for GC plan/apply (`--yes`), cost report, quota, reconcile, alert list, and alert acknowledgement using exact JSON output.
- [x] 5.4 Add composition, CLI/service, authorization, invalid-input, cross-tenant, read-only, and no-second-store architecture tests.

## 6. End-To-End And Scale Verification

- [x] 6.1 Add a production-shaped enforced Research run that proves quota/usage/catalog facts and a reproducible daily cost report across accepted and gate-failed outcomes.
- [x] 6.2 Add cross-run dedup/retention/GC integration proving active evidence/replay protection, stale-plan rejection, one physical purge, catalog cleanliness, and restart from injected GC crash points.
- [x] 6.3 Add concurrent multi-run/class quota and 100-branch catalog/GC stress coverage with deterministic totals and no duplicate physical deletion or orphan from quota rejection.
- [x] 6.4 Prove `read_only`, `shadow`, `legacy`, and rollback-readable policy behavior: inspection/reporting remains available while unauthorized materialization or GC apply performs zero writes.
- [x] 6.5 Run architecture/source validation and adversarial checks for raw payload/secret/path leakage in usage, report, alert, operation, CLI, and error serialization.

## 7. Completion Gates

- [x] 7.1 Run `openspec validate graph-artifact-cost-retention --strict`, targeted suites, compile, and mandatory `python -m scripts.dev smoke`; fix root causes.
- [x] 7.2 Record final verification evidence, sync main specs, archive the completed change, and preserve the later retention-window/legacy-writer removal boundary.

## Final Verification Evidence

- Implementation commit: `9646bf71` (`feat(harness): harden graph artifact governance`) plus the preceding phase commits recorded in Git history.
- Targeted framework/infrastructure governance regression: `219 passed, 2 skipped`.
- Targeted Research production/composition/CLI regression: `110 passed`.
- Architecture regression: `134 passed`.
- Mandatory offline smoke: `2309 passed, 23 deselected, 22 warnings`; source validation reported `is_valid=true`, `error_count=0`, `warning_count=0`.
- `python -m scripts.dev compile`, `python -m scripts.dev sources-validate`, and `openspec validate graph-artifact-cost-retention --strict` all passed.
- This change does not claim a complete production retention window and does not remove the legacy Workflow artifact writer. Production/shadow retention evidence, historical-data disposition, and legacy-writer removal remain a later explicit OpenSpec change.
