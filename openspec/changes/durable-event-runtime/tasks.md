## 1. Baseline And Migration Fixtures

- [x] 1.1 Inventory every production event model, event type, writer, reader, subscriber, storage adapter, public import, checkpoint offset, API/CLI/MCP response, and historical JSONL variant; record keep/adapt/delete ownership and freeze representative fixtures.
- [x] 1.2 Archive or baseline the completed capabilities directly modified by this change, especially event-store, workflow event indexing, checkpoint/replay, and run-event interface requirements, without editing completed change history in place.
- [x] 1.3 Convert the confirmed shallow-mutation, context-conflict, recorder-dual-ledger, partial-delivery, duplicate-replay, secret-export, missing-time, and PostgreSQL `COUNT(*)` race reproductions into failing regression or conformance tests.
- [x] 1.4 Add a migration dry-run command that scans legacy run JSONL, local event records, PostgreSQL rows, checkpoints, and Harness histories and reports importable, duplicate, conflicting, unknown-schema, missing-time, and quarantined counts without mutating source data.

## 2. Canonical Event Contract

- [x] 2.1 Add the canonical `StoredEvent`, business context, producer identity, trace block, payload reference, schema identity, security classification, distinct content/record checksums, and typed error models under `framework/events` with no infrastructure imports.
- [x] 2.2 Implement canonical JSON normalization, recursive immutable views, the specified content-checksum include/exclude projection, complete-record-checksum coverage, payload/extension limits, and tests proving mutations cannot alter accepted content and same-id changes to stream, tenant, schema, classification, context, or payload reference are collisions.
- [x] 2.3 Implement one authority rule for business and trace fields; add compatibility parsing that accepts equal legacy duplicates and rejects or quarantines conflicts.
- [x] 2.4 Implement `EventSchemaCatalog`, current workflow/Harness schema registrations, payload validators, pure ordered upcasters, sensitivity policies, and historical fixture tests including unknown-version quarantine and missing-time handling.
- [ ] 2.5 Implement the shared security projector before all store adapters and exports, reserved-field protection, tenant/classification propagation, and no-secret persistence/diagnostic tests; allow ordinary artifact refs only for schema-permitted oversized non-sensitive data and fail closed for reference-only/confidential/restricted content unless a separately authorized, encrypted, integrity-checked, audited secure payload store is composed.

## 3. Durable Storage Ports And Schemas

- [x] 3.1 Define framework-owned event runtime/store/reader/unit-of-work protocols for atomic append, ordered reads, identity lookup, pagination, delivery ledger, inbox, checkpoint, dead letter, quarantine, and replay access.
- [x] 3.2 Add an additive SQLite schema and adapter using WAL, foreign keys, unique constraints, bounded busy timeout, transactional sequence allocation, integrity checks, and explicit single-host support documentation.
- [x] 3.3 Define and test SQLite durability behavior for commit, process death, database lock timeout, read-only filesystem, disk-full failure, corrupt database, backup/recovery, and synchronous/fsync policy; fail before publication when durability is unavailable.
- [x] 3.4 Add a new PostgreSQL migration for canonical events, stream sequence state, pending deliveries, inbox, consumer checkpoints, leases, dead letters, quarantine, and replay reports without modifying deployed migration `001_initial.sql`.
- [x] 3.5 Replace PostgreSQL `COUNT(*)` offset allocation with transaction-safe per-stream sequence allocation and make duplicate `event_id` return the existing committed sequence only when checksum matches.
- [x] 3.6 Apply the same pre-storage security projection to PostgreSQL and SQLite, then run one adapter conformance suite proving byte-equivalent canonical payload/checksum and matching error semantics.
- [x] 3.7 Update `event_store_from_env()` so `NEWS_DATABASE_DSN` selects PostgreSQL and local composition selects SQLite; retain JSONL stores only as legacy import/export compatibility adapters.

## 4. Durable Publish And Delivery Runtime

- [x] 4.1 Implement `EventRuntime.publish()` so validation, projection, stable content checksum, store-assigned observation time/sequence, final record checksum, canonical append, and pending consumer work commit atomically before subscriber visibility.
- [ ] 4.2 Implement durable versioned consumer subscriptions with independent `(subscription_id, version, stream_id)` checkpoint/delivery identity, deterministic filters, `EARLIEST`/`LATEST`/`AT_SEQUENCE`, pause materialization/resume drainage, retire watermark/drain-or-cancel, and registration-versus-publication race tests proving no boundary gap or duplicate delivery row.
- [x] 4.3 Implement `ACK`/`RETRY`/`DROP`, with `DROP` restricted to policy-approved non-error skips and permanent processing failure routed directly to DLQ; test isolated consumer progress and prove one failure does not block or roll back other consumers.
- [x] 4.4 Implement stable `consumer_effect_id`, inbox uniqueness, and helpers coupling `(event_id, consumer_effect_id)` or an equivalent idempotency key to external effects; reject activation or first delivery for an external-effect subscription without a valid idempotency contract and test automatic retry, lease recovery, requeue, and redelivery.
- [x] 4.5 Implement bounded exponential retry with cap and jitter, terminal dead letters, redacted failure diagnostics, and tests for success within budget, poison events, exhaustion, and dead-letter write failure.
- [ ] 4.6 Implement leased delivery claims with generation/fencing, crash recovery, stale-ack rejection, highest-contiguous-terminal checkpoints, same-subscription-stream claim ordering, and auditable terminal gaps; implement authorized requeue as a non-frontier-moving late-repair generation with out-of-order-repair capability checks, inbox-preserving ACK redelivery, and compensation/new-version fallback tests.
- [ ] 4.7 Implement per-consumer batch, in-flight, and concurrency limits plus pending count, lag, and oldest-age signals; test slow consumers, backlog, storage admission failure, and recovery without unbounded memory growth.
- [ ] 4.8 Define event-runtime diagnostic fallback so failure of the event store or telemetry path writes one bounded nonrecursive local/process diagnostic and never attempts to report the failure through the same unavailable event path indefinitely.

## 5. Workflow And Harness Cutover

- [ ] 5.1 Replace workflow recorder dual `_records/_envelopes` state with a scoped durable emitter that receives immutable trace/business context per append and cannot leak step context across parallel execution.
- [ ] 5.2 Validate `run_id` as a single path-safe segment before stream derivation or any store/projection path resolution, then persist workflow events during execution, store last durable sequence in checkpoints, generate redacted `events.jsonl` from the canonical stream, and record projection watermark/checksum; test traversal, absolute, drive-relative, UNC/device, ADS, and reserved-device rejection before all writes.
- [ ] 5.3 Disable and delete post-run JSONL-to-store indexing, runner-local event model/store/factory, and duplicate workflow/inspection record definitions after compatible projections are in place.
- [ ] 5.4 Adapt typed `HarnessEvent` and `HarnessEventLogEntry` to the canonical durable boundary and make every recoverable Harness transition commit before projection advances, including phase entry/exit, replan, retry, route-to-repair, wait, approval resume/cancel, budget exhaustion, halt, failure, and success.
- [ ] 5.5 Prove Harness and workflow fail closed rather than downgrade to memory-only when a required durable transition cannot commit, while deterministic required work remains a direct service call instead of an observational subscriber.
- [ ] 5.6 Update checkpoint migration and recovery so 0-based legacy offsets and 1-based stream sequences are explicitly mapped without skipping or applying the boundary event twice.

## 6. Deterministic Replay

- [ ] 6.1 Implement `REBUILD_STATE`, `VERIFY_HISTORY`, and authorized `REDELIVER` entrypoints with separate policies and remove production use of replay-to-live-bus behavior.
- [ ] 6.2 Implement pure reducer registration, ordered schema/integrity validation, checkpoint plus `after_sequence` resume, a transactionally captured finite source high watermark, source-history immutability, and durable replay reports.
- [ ] 6.3 Record activity contracts for LLM, Tool, MCP, HTTP, retrieval, memory write, artifact publication, real clock, and random outcomes and make replay consume recorded references instead of invoking live operations.
- [ ] 6.4 Implement workflow/reducer/policy/schema/activity version resolution and deterministic command comparison with typed mismatch, missing-activity, corrupt-history, and incompatible-version reports.
- [ ] 6.5 Add failure tests for replay interruption/resume, replay concurrent with live append proving events above the captured watermark are excluded, corrupted checkpoints, unsorted input, unknown schema, upcaster failure, missing activity result, and poison-event redelivery.

## 7. OpenTelemetry And W3C Propagation

- [ ] 7.1 Add an optional standards-compatible trace adapter and no-op fallback; migrate new trace/span generation to valid W3C identifiers while preserving legacy identifiers as noninjectable historical correlation data.
- [ ] 7.2 Implement shared extract/child/inject propagation at HTTP, MCP inbound, ToolRuntime outbound MCP/HTTP, worker, and message boundaries with trust validation, baggage/tracestate limits, and security tests.
- [ ] 7.3 Map service/process identity to OpenTelemetry Resource, library/component identity to InstrumentationScope, and asynchronous fan-out/fan-in/batch/retry causality to span links.
- [ ] 7.4 Preserve the bounded `TraceContext.root()`, `child()`, serialization, and `trace_fields()` compatibility facade while propagating all supported Agent, Tool, Memory, and Artifact business IDs, removing shared mutable recorder context, and testing schema-aware sensitive handling without substring false positives or credential-key omissions.
- [ ] 7.5 Verify trace sampling or missing OpenTelemetry dependencies never suppress durable events, change workflow behavior, or expose raw payloads and high-cardinality tenant/user/run/event identifiers as metric labels.

## 8. Query, Export, And Operator Interfaces

- [ ] 8.1 Add an application-owned event reader/operations service for run queries, projection export, quarantine, replay, and dead-letter actions; keep interfaces independent of concrete stores and dispatchers.
- [ ] 8.2 Cut `RunInspectionService` online reads to the durable reader while preserving compatible run id, event count, events, path, type/step filters, limit/offset, CLI, MCP, and HTTP response fields and adding stable sequence pagination.
- [ ] 8.3 Define and test API/SSE/CLI/MCP behavior when the store is unavailable or a JSONL projection is stale, including explicit availability/staleness metadata rather than silent authoritative fallback.
- [ ] 8.4 Generate deterministic redacted `events.jsonl` projections and offline rebuild tooling from a requested durable high watermark without feeding the export back into the live store.
- [ ] 8.5 Add authorized, tenant-scoped operator surfaces for quarantine inspection, replay reports, dead-letter list/requeue/resolve, consumer lag, and projection status through application services.

## 9. Migration Cutover And Deletion

- [ ] 9.1 Backfill a staging canonical store from historical JSONL/local/PostgreSQL/Harness records, verify counts, sequence mapping, checksums, and quarantine reports, and leave all source history unchanged.
- [ ] 9.2 Add an explicit shadow-read/export comparison phase that never dispatches twice, then cut workflow and Harness writes to the durable runtime and disable old post-run indexing in the same release boundary.
- [ ] 9.3 Cut reads to the durable source, verify API/CLI/MCP/checkpoint compatibility, and retain deprecated framework imports/callable subscriber adapters for exactly one documented migration release.
- [ ] 9.4 Remove framework legacy `EventRecord`, duplicate context storage, dual recorder lists, mixed subscriber payloads, runner-local stores/models/factory, live-bus replay, and obsolete JSONL authority after all production callers and migration fixtures pass.
- [ ] 9.5 Execute the phase-specific rollback drill and prove rollback preserves accepted events and sequences, does not repeat external effects, does not disable schema/security checks, and can rebuild compatible projections.

## 10. Verification And Delivery Gates

- [ ] 10.1 Run all `tests/framework/events`, event/trace contracts, Workflow/Harness runtime, checkpoint, manifest, inspection, storage event, and API/CLI/MCP targeted suites including every new adversarial and fault-injection case.
- [ ] 10.2 Run real SQLite multi-process/single-host fault tests and real PostgreSQL concurrent-writer/transaction/crash integration tests; FakeConnection-only tests do not satisfy this gate.
- [ ] 10.3 Measure and record the PRD append/delivery/recovery SLO benchmark under the fixed workload, verify size/backlog limits, and attach machine/configuration evidence.
- [ ] 10.4 Run `openspec validate durable-event-runtime --strict`, `python -m scripts.dev compile`, `python -m scripts.dev smoke`, `openspec validate --all --strict`, and `git diff --check`; fix root causes for every failure.
- [ ] 10.5 Update PRD implementation status, completed task evidence, migrations, commits, benchmark results, and rollback drill only after every Definition of Done item is satisfied, then commit each implementation batch without unrelated worktree changes.
