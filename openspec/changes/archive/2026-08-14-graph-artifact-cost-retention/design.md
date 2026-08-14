## Context

The Graph artifact runtime has one physical Research filesystem store, a verified Local JSON catalog, deterministic catalog GC planning, and a file-backed SQLite result store that owns attempt envelopes, run quota reservations, and expiring cache entries. The catalog can add and remove logical references but deliberately cannot execute GC. The result store enforces only run-level byte/count limits, and materialization/context observations are not durable enough to build a reproducible cost report.

This change is the Phase 8 prerequisite for shadow acceptance and legacy writer removal. It must preserve `LLM/subagent as worker, Harness as control plane`, keep report/publication gates authoritative, remain offline-capable, and avoid introducing a second artifact body store. Framework contracts must remain backend neutral; filesystem, SQLite, Research, and CLI code stay in their existing infrastructure/interface owners.

## Goals / Non-Goals

**Goals:**

- Enforce byte/count quota simultaneously by tenant, run, and `ArtifactClass` with exactly-once reservation and settlement.
- Make every cost-relevant materialization, cache access, context load, read-back failure, catalog drift observation, and GC transition a sanitized idempotent durable fact.
- Generate deterministic daily cost reports and threshold alerts from catalog snapshots plus a durable usage watermark.
- Turn side-effect-free catalog GC planning into an explicit, restart-safe, concurrent-safe apply workflow.
- Preserve active run, report, evidence, publication, and replay ownership until an authorized lifecycle transition releases it.
- Expose the same real governance runtime to Research production composition and operator commands.

**Non-Goals:**

- No new artifact body store, remote object-store SDK, metrics vendor, scheduler daemon, or notification vendor integration.
- No automatic deletion of legacy Workflow artifacts or historical compatibility fixtures.
- No LLM-selected quota, retention, GC, alert, report, or lifecycle decision.
- No weakening of Research quality gates, terminal publication authority, tenant checks, read-back verification, or rollout fail-closed behavior.
- No claim that a production retention window has elapsed; that evidence and legacy writer removal remain a later change.

## Decisions

### Harness owns one governance runtime over existing ports

`GraphArtifactGovernanceRuntime` is a deterministic Harness service. It receives backend-neutral catalog, physical lifecycle, governance ledger, run-lifecycle authority, and clock ports. It owns the sequence for retention release, GC plan/apply, cost report generation, and alert evaluation. Interface code calls this service; it does not reach directly into the catalog, filesystem, or SQLite tables.

The data flow is:

```text
ResultMaterializer / ArtifactContextLoader
        | exact usage and quota facts
        v
SQLiteGraphResultStore (attempt + quota + usage + GC operation ledger)
        |
        +---- catalog snapshot/checksum ----+
        |                                   v
LocalJsonArtifactCatalog <---- GraphArtifactGovernanceRuntime ----> cost report / alerts
        |                                   |
        +---- exact GC detach lease --------+
                                            v
                             Filesystem graph-result lifecycle port
```

Putting orchestration in the legacy `StorageApplicationService` was rejected because that service owns the older artifact index and type-name retention policy, not Graph catalog identities. A second Graph artifact store was rejected because it would split physical truth and make dedup/GC unsafe.

### Configuration adds bounded aggregate quota and governance thresholds

`GraphArtifactPersistenceConfig` keeps the existing run limits and five-class `GraphArtifactRetentionSettings`. It adds tenant byte/count limits, per-`ArtifactClass` byte/count limits, a quota warning ratio in basis points, a GC backlog byte threshold, and a cache-miss stampede threshold. All values have code-level lower/upper bounds and are part of the immutable policy snapshot.

The same class limit applies independently to each `ArtifactClass` unless a later policy version introduces an explicit class table. This keeps the first production schema bounded and deterministic while still enforcing the required tenant/run/class dimensions. Worker payloads cannot supply or override any value.

### SQLite remains the single result and governance ledger

`SQLiteGraphResultStore` is upgraded in place with a versioned transaction migration. A quota reservation records trusted graph/node identity, artifact class, retention class, and policy version in addition to tenant/run and bytes/count. Reservation checks run, tenant, and tenant-plus-artifact-class aggregates in one `BEGIN IMMEDIATE` transaction. Pending reservations remain charged after restart; failed settlements release charge; successful settlement replaces estimated values with exact values. Reconciliation can release a pending reservation only when durable attempt/catalog evidence proves that no successful object exists, never from elapsed time alone.

A new exact-schema usage table stores idempotent `GraphArtifactUsageFact` records. Its identity is derived from the trusted operation identity and fact kind, not a random id. Facts contain correlation ids, class, policy version, integer bytes/tokens/counts, outcome, and controlled reason/error codes only. Candidate bodies, prompt text, tool payloads, secrets, paths, and raw exception strings are forbidden.

GC operations, deleted-entry tombstones, report snapshots, alerts, and alert acknowledgements use the same database and transaction discipline. Extending the existing database was chosen over separate files because quota, usage, and GC recovery need compare-and-set and first-writer-wins behavior. Existing schema version 1 databases are migrated without rewriting attempt envelopes or changing their checksums; rollback readers continue to support policy versions declared in configuration.

### Cost accounting is required at the action boundary

Materializer artifact/cache actions reserve class-aware quota before a physical write. Settlement and its materialization usage fact commit atomically. Inline/omitted outcomes and failures before reservation use the durable usage port with a binding-derived id. The existing best-effort observation callback remains diagnostic only and cannot be the source of cost truth.

`ArtifactContextLoader` receives a durable usage port in production. After exact read-back and budget verification, it records the plan/result checksum, actual loaded bytes/tokens, purpose, mode, tenant/run/graph/node, and policy version before returning the context result. Retrying the same load writes the same fact. A usage-ledger failure in `enforce` or `read_only` fails the accounted operation with a typed sanitized error; tests may inject an explicit fake port.

Cache reports count only explicit durable `hit` and `miss` facts. A cache write followed by verification is not mislabeled as a worker-saving hit. If a reporting window contains no cache lookup facts, the hit ratio is `null` with zero hit/miss counts rather than a fabricated percentage.

### Catalog snapshot evidence gates every deletion

The catalog exposes a typed immutable snapshot checksum and enriches each GC decision with the exact canonical entry, logical claim ids, logical reference ids, active protection evidence, and decision checksum. A delete candidate still requires expired retention and zero active references. Cache/ephemeral references expire at their declared timestamp. Run/evidence/replay references are released only after a trusted lifecycle authority proves a terminal run and the owning claim retention has elapsed. Report/publication references with indefinite retention require an explicit publication-retirement authority.

The existing catalog state format remains the current object/reference truth. GC history and tombstones live in the SQLite governance ledger, not in a second artifact store. This avoids leaving dangling catalog claims after physical deletion and keeps ordinary lookup/reconciliation deterministic.

### GC apply uses a durable detach-and-quarantine state machine

Planning is always side-effect-free. `prepare_gc` persists the complete plan and catalog snapshot checksum. Applying one decision follows this bounded state machine:

```text
prepared -> catalog_detached -> quarantined -> purged -> completed
      |             |
      +-> stale     +-> retryable_failure
```

1. Persist an operation intent containing the exact plan item and catalog snapshots.
2. Under the catalog file lock, re-evaluate the item against the current snapshot. If any claim/reference/protection changed, mark it `stale` and do not touch bytes.
3. Atomically detach the canonical entry and all now-inactive claims/references from the live catalog. That detach is the deletion lease: a concurrent new registration creates a new physical identity/ref instead of reviving the detached object.
4. The filesystem lifecycle adapter verifies the exact internal graph-result ref, checksum, byte size, and run binding, removes its manifest member, and atomically renames the file into an operation-scoped quarantine path on the same volume.
5. Persist the quarantine receipt, purge the quarantined bytes, then persist the completed tombstone and usage fact.

Every transition is compare-and-set and idempotent. Restart resumes from the last durable state. A crash after catalog detach is recoverable from the stored intent; a crash after rename finds the operation-scoped quarantine file; a crash after purge relies on the already committed quarantine receipt. Two executors for the same operation converge on one result, while a different or stale plan cannot reuse the operation identity.

Deleting directly from the existing filesystem store before catalog mutation was rejected because a new cross-run reference could race the delete. Holding a Local JSON lock across filesystem I/O was rejected because it creates an unbounded critical section and cannot make two files atomic.

### Reports combine a catalog snapshot with a ledger watermark

`DailyGraphArtifactCostReport` covers one closed UTC interval and records the policy version, catalog snapshot checksum, maximum usage sequence, generated-at timestamp, and report checksum. Stable sorted dimensions include tenant, run, graph, node, artifact class, and policy version.

Logical bytes/count are based on logical claims and materialization facts; unique physical bytes/count are based on canonical entries and completed tombstones; dedup savings use integer basis points; expired bytes come from the matching GC plan; cache hit/miss comes from explicit cache facts; failed writes and context-load bytes/tokens come from usage facts. Global unique bytes are counted once, while each scoped group reports the unique physical identities reachable from that scope. Regeneration with the same snapshot and watermark produces byte-identical output.

Reports for an open UTC day are explicitly `provisional`; closed-day reports are immutable for a given input watermark. Late facts produce a new revision with a new watermark rather than overwriting an earlier report.

### Alert evaluation is pure; delivery is durable and replaceable

The alert evaluator consumes quota snapshots, a cost report, a GC plan, and a reconciliation result. It emits stable alert records for run/tenant quota at or above the configured ratio, GC backlog, any production read-back failure, any catalog drift, and repeated cache misses for the same trusted cache identity. Alert ids are derived from type, reporting window, tenant/scope, and policy version. Re-evaluation is idempotent; acknowledgement is a separate compare-and-set record and never deletes the underlying alert.

The local production delivery is the durable SQLite alert inbox exposed by operator queries. A future metrics/notification adapter can implement the alert sink port without changing Harness decisions. Logging contains only bounded ids, sizes, classes, ratios, and reason codes.

### Production and operator composition are explicit

Research production composition constructs the catalog, the upgraded SQLite result/governance store, the filesystem graph-result lifecycle adapter, and one governance runtime from the same immutable settings snapshot. `enforce` records all write/read usage; `read_only` permits inspection, report generation, and replay reads but no new materialization or GC apply; `shadow` can compute policy/usage comparisons without physical deletion; `legacy` does not silently create Graph governance state.

Operator commands expose GC plan, GC apply with explicit `--yes`, cost report, alert list/acknowledge, and reconcile. They share the production factory and return machine-readable exact-schema output. No command accepts a worker-produced plan or deletes an arbitrary path/ref.

## Risks / Trade-offs

- [Catalog metadata is detached before physical purge, so a crash temporarily leaves orphan bytes] -> Persist the complete intent first, quarantine by deterministic operation id, resume automatically, and suppress only the matching in-flight orphan from drift alerts.
- [A stale plan could delete newly referenced content] -> Recompute and compare the exact snapshot under the catalog lock immediately before detach; any change produces `stale` with zero physical mutation.
- [Pending reservations can hold quota after a crash] -> Keep them charged by default and release only through evidence-backed reconciliation, never by TTL alone.
- [Cost aggregation across deduplicated runs can be misinterpreted] -> Report global unique bytes once and include separate scoped reachable-unique values plus explicit ratio definitions.
- [Usage accounting can add write latency] -> Batch only independent facts, retain WAL/busy-timeout settings, index report dimensions, and keep payloads compact and integer-only.
- [Old code cannot understand newly added quota dimensions] -> Migrate SQLite transactionally, preserve existing envelope/checksum rows, and document read-only rollback constraints before enabling GC apply.
- [A production alert sink can fail] -> Commit the durable local alert first; external delivery is replaceable and does not control routing, GC, or quality decisions.

## Migration Plan

1. Add framework governance contracts, configuration bounds, typed reports/alerts, catalog snapshot/detach requests, and architecture tests.
2. Migrate `SQLiteGraphResultStore` to the new quota/usage/GC schema with version-1 fixture tests, integrity checks, and concurrent reservation tests.
3. Extend `LocalJsonArtifactCatalog` with snapshot evidence, lifecycle release, and exact GC detach while preserving current registration/dedup state compatibility.
4. Add the filesystem quarantine lifecycle adapter and crash/restart/concurrency tests.
5. Wire materializer/context usage accounting and production Research composition; run enforce/read-only restart tests.
6. Add the governance runtime and operator plan/apply/report/alert interfaces. Enable plan/report first; keep apply behind explicit confirmation.
7. Run strict OpenSpec validation, targeted suites, compile, mandatory smoke, and archive the change.
8. Roll back by switching materialization to `read_only` or `legacy` and disabling GC apply. Never restore purged bytes automatically; retained reports, tombstones, and previous policy readers remain readable.

## Open Questions

- Automated scheduling cadence and external notification transports are deployment concerns; this change provides deterministic callable operations and a durable local alert inbox.
- Worker-saving pre-execution cache reuse needs a trusted dependency identity before worker dispatch. This change reports only explicit cache lookup facts and does not count write/read-back verification as a hit.
- Legacy writer removal still requires a complete production/shadow retention window and a separate `remove-legacy-workflow-artifact-writer` change.
