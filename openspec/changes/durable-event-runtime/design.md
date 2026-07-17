## Context

NewsRoom currently has several partially overlapping event representations and persistence paths:

- `framework.events.Event`, `EventEnvelope`, and the legacy workflow `EventRecord`;
- `infrastructure.storage.events.EventRecord` plus local JSON and PostgreSQL stores;
- workflow-runtime and inspection-specific event records;
- Harness control-plane events and an in-memory `HarnessEventPort`;
- subsystem-specific Agent, Tool, Memory, and tracing events.

The live workflow path records to two in-memory lists, optionally dispatches through a synchronous fail-fast bus, writes `run/<run_id>/events.jsonl` at finalization, and then reads that file back after the run to populate another event store. Run inspection reads the run artifact again rather than the storage-owned event stream. This creates multiple sources of truth and leaves a crash window before finalization/indexing. The PostgreSQL store allocates offsets with `COUNT(*)` before insert, which is not safe for concurrent writers, while the local JSON store has no transaction, tail-recovery, or durable consumer state.

The architecture requires every Harness phase transition to be durable and replayable, but tracing must remain an observability signal rather than the business source of truth. Existing API, CLI, MCP, checkpoint, manifest, and `events.jsonl` contracts must remain readable during migration. Framework code must define ports and deterministic policy; infrastructure owns persistence adapters; interfaces continue to call application services.

## Goals / Non-Goals

**Goals:**

- Establish one canonical stored event envelope while allowing domain modules to retain typed event classes.
- Persist an accepted event and its pending delivery work before live subscribers observe it.
- Guarantee a monotonic order within one stream and explicitly avoid claiming a global order.
- Provide at-least-once delivery with idempotent consumer effects, bounded retry, dead letters, and resumable checkpoints.
- Make state reconstruction and verification replay deterministic and side-effect-free by default.
- Validate event schemas at ingress, support controlled upcasting, and quarantine incompatible history.
- Apply security projection before durable writes and exports.
- Use OpenTelemetry and W3C Trace Context for propagation without coupling durable identity to sampled trace data.
- Preserve compatible run inspection and `events.jsonl` export surfaces while changing their source of truth.

**Non-Goals:**

- Introducing Kafka, Temporal, Dapr, or a new hosted broker in this change.
- Guaranteeing a total order across streams.
- Claiming exactly-once execution for email, HTTP, MCP, LLM, Tool, database, or other external side effects.
- Converting every NewsRoom domain aggregate to Event Sourcing.
- Using telemetry as an audit log or replay source.
- Adding a new UI, replacing existing run authorization, or defining cross-region replication.
- Retaining a permanent compatibility layer after all owned callers and historical data have migrated.

## Decisions

### 1. Typed domain events converge at one stored-envelope boundary

Domain modules may keep typed input/result classes, but every durable write is converted to one `StoredEvent` contract. Delivery attempts and consumer state are not fields on the immutable event; they live in a separate delivery ledger.

The canonical logical shape is:

```text
StoredEvent
  envelope_schema              # newsroom.event-envelope/v2
  event_id                     # stable before first append
  event_type                   # registered semantic name
  data_schema                  # registered payload schema and version
  source                       # producer namespace, not destination
  subject                      # affected entity inside source scope
  occurred_at                  # when the fact happened
  observed_at                  # store-assigned ingestion time
  stream_id                    # ordering/replay scope
  stream_sequence              # store-assigned, 1-based and monotonic
  correlation_id               # groups related work
  causation_id                 # event that directly caused this event
  business_context
    run_id / workflow_id / step_id
    task_id / agent_id / tool_call_id / request_id
  producer
    component / version / instance_id
  trace
    trace_id / span_id / trace_flags / tracestate / is_remote
  tenant_id
  security_classification
  content_type
  payload | payload_ref
  extensions
  content_checksum
  record_checksum
```

`content_checksum` covers the complete canonical pre-storage acceptance projection: envelope and data schema identities, event identity/type/source/subject, occurrence time, stream identity, correlation/causation, business context, producer, trace, tenant/classification, content type, the post-security payload or payload reference and expected checksum, and extensions. It excludes only store-assigned `observed_at` and `stream_sequence`, both checksum fields, and delivery/checkpoint/lease/replay/operator state. It is stable across an uncertain-commit retry and is used to resolve `event_id` idempotence. `record_checksum` is calculated only after the store assigns observation time and sequence and covers the complete immutable stored record, including `content_checksum`, except `record_checksum` itself. The conformance suite proves that changing stream, tenant, schema, classification, context, or payload reference while reusing an event ID is a collision even when the inline payload is equal.

Core context exists in exactly one canonical location. Legacy flat projections may duplicate fields only during serialization compatibility and must reject a conflict rather than choose one silently. `causation_id` refers to an event; `parent_span_id` remains a tracing concept and is not a substitute.

Alternatives rejected: a single untyped metadata dictionary cannot establish ownership or validation; forcing every domain model to inherit one base event couples business code to storage; continuing `Event` plus `EventEnvelope` context duplication preserves the current ambiguity.

### 2. Payloads become canonical immutable snapshots

Before an event receives its content hash, the runtime converts supported JSON-like input into a canonical JSON value, recursively freezes the in-memory view, rejects unsupported values, and computes `content_checksum` after security projection. The store later computes `record_checksum` after it assigns the observation time and sequence. Mutating the caller's original dictionary or a returned view cannot change either accepted checksum.

Inline payloads default to at most 64 KiB after UTF-8 canonical serialization; extensions default to 32 keys and 8 KiB total. Oversized non-sensitive content may use a schema-permitted integrity-protected `payload_ref`. Reference-only, confidential, or restricted content may use a reference only when the referenced store proves tenant-scoped authorization, encryption in transit and at rest, checksum verification, and audited access. The current ordinary `ArtifactReference` and local artifact path do not provide that security boundary, so the first release fails closed for protected content unless a separate secure payload store is composed. Limits are configurable but never disabled implicitly.

Alternatives rejected: `dict()` and `deepcopy()` do not make the exposed event immutable; silently stringifying arbitrary objects produces unstable schemas; embedding large LLM/tool payloads makes replay and operator queries unsafe and expensive.

### 3. Schema identity is separate from envelope identity

`envelope_schema` versions the shared event wrapper. `data_schema` versions the event payload. A deterministic `EventSchemaCatalog` maps `(event_type, data_schema)` to a validator, compatibility metadata, sensitivity policy, and ordered upcasters.

The catalog registers existing names such as `workflow_started` as supported v1 aliases so migration does not require a flag-day rename. New event types use a namespaced convention. Compatible changes remain within the same semantic event type; incompatible payload meaning requires a new schema major version and, where meaning changes, a new event type.

Unknown schemas, failed validation, missing historical occurrence times, and ambiguous duplicate fields enter quarantine with a typed reason. They are not assigned a current timestamp, guessed identity, or silently passed to consumers. Upcasters are pure, version-to-version functions and historical fixtures prove every supported chain.

Alternatives rejected: treating `schema_version` as a free-form label provides no compatibility; allowing consumers to interpret arbitrary payloads makes migration nondeterministic; rewriting stored history destroys audit identity.

### 4. Append is authoritative; dispatch follows durable acceptance

`EventRuntime.publish()` performs this order:

```text
create stable event_id
-> normalize and validate
-> apply security projection
-> atomically allocate observed_at and stream_sequence
-> compute final record_checksum
-> append immutable event + pending delivery work
-> commit
-> return StoredEvent
-> dispatcher delivers independently per consumer
```

An append of the same `event_id` and identical `content_checksum` is idempotent and returns the existing event and its original sequence. Reusing an `event_id` with a different `content_checksum` raises an identity-collision error. An event is never visible to a subscriber before the append transaction commits.

For workflow and Harness execution, the default stream is `run:<run_id>`. The `run_id` must be validated as one path-safe segment before deriving that stream ID or resolving any durable-store or projection path. Other durable aggregates use an explicit namespace such as `agent-session:<session_id>`. Order is guaranteed only within one stream. `stream_sequence` starts at 1; a subscription-version checkpoint stores the highest contiguous terminal frontier for its stream; a legacy JSONL offset remains a 0-based projection and is never used as the canonical identity.

Alternatives rejected: timestamps cannot order concurrent facts; an in-process counter cannot survive restart; publishing first and persisting later reproduces partial delivery and loss windows.

### 5. Framework owns ports; SQLite and PostgreSQL own durable adapters

`framework/events` defines `EventRuntimePort`, `EventStorePort`, `EventSchemaCatalog`, `EventConsumer`, replay policies, typed outcomes, and errors. It does not import `infrastructure`.

The local durable backend becomes SQLite using the standard-library driver, WAL mode, foreign keys, unique constraints, bounded busy timeout, and transactions. The current `LocalJsonEventStore` becomes a legacy importer/exporter and read-compatibility adapter; it is not the multi-writer source of truth. PostgreSQL remains the shared/deployment backend and receives a new additive migration rather than edits to deployed migration `001_initial.sql`.

Both backends pass one conformance suite covering:

- atomic stream-sequence allocation;
- event-id idempotence and collision rejection;
- ordered reads and bounded pagination;
- outbox claims and leases;
- inbox uniqueness;
- consumer checkpoints;
- retry scheduling and dead letters;
- transaction rollback and crash recovery.

`event_store_from_env()` remains the composition entrypoint: `NEWS_DATABASE_DSN` selects PostgreSQL; otherwise it selects local SQLite under the configured storage root. Workflow runtime no longer defines storage implementations inside `runner.py`.

Alternatives rejected: adding locks and transaction sidecars to JSONL recreates a database poorly; requiring PostgreSQL for every local run harms developer workflows; introducing Kafka is disproportionate before the in-process contracts and correctness semantics converge.

### 6. Delivery is explicitly at-least-once

Each consumer has a stable `consumer_id` and returns one terminal or nonterminal outcome:

```text
ACK(reason?)       # effect completed; contiguous frontier may advance
RETRY(reason)      # schedule another bounded attempt
DROP(reason)       # deterministic policy-approved non-error skip
```

Unhandled exceptions map to `RETRY` unless a typed policy classifies them as permanent. A permanent processing failure enters the dead-letter state immediately; `DROP` cannot be used to bypass failure diagnostics or DLQ controls. Default retry policy is five total attempts, exponential delay from 1 second, 60-second cap, and 20% jitter; a consumer can declare a stricter policy. Exhaustion creates a dead-letter record containing event identity, consumer identity, attempts, first/last failure timestamps, error classification, and operator disposition. It never copies unredacted payloads into error text.

Each subscription declares whether it performs external effects and a stable `consumer_effect_id`. The inbox unique key `(event_id, consumer_effect_id)` protects a logical business effect across subscription versions and delivery generations. Before an external-effect subscription is activated or receives its first delivery, composition must validate that key, an equivalent database uniqueness constraint, or an external API idempotency key coupled to the effect transaction. A consumer without that proof cannot be activated; operator authorization does not make automatic retry or lease recovery safe. The runtime does not call this end-to-end exactly-once.

Consumers are isolated: one failure does not stop other consumers. Normal work for one `(subscription_id, version, stream_id)` is claimed in sequence, so sequence N+1 cannot pass unresolved sequence N; different streams may run concurrently. The checkpoint key is `(subscription_id, version, stream_id)` and advances only to the highest sequence for which all earlier matching deliveries have an auditable terminal disposition. Delivery identity also includes subscription version and delivery generation, while effect-inbox identity remains independent. Dispatcher claims are leased and recoverable after worker death. Bounded batch size and per-consumer concurrency provide backpressure. Accepted durable events are never silently dropped; admission or storage-limit failures occur before the append commits.

Deterministic work that the workflow requires synchronously is a normal service call, not an observational subscriber.

Consumer registration is itself durable and versioned. A subscription declares deterministic event/schema filters and an explicit start policy: `EARLIEST`, `LATEST`, or `AT_SEQUENCE`. Registration/backfill and concurrent publication use transactional subscription state plus unique delivery constraints so the consumer neither misses the boundary event nor receives duplicate delivery rows. Pause stops new claims but continues materializing matching delivery rows; resume drains them from the unchanged frontier. Retirement transactionally fixes a watermark, stops later materialization, and drains or explicitly terminally cancels existing rows. Changing a start position or filter creates a new version with independent checkpoint/delivery history rather than rewriting prior progress.

A dead letter is a terminal disposition for the normal frontier, so later sequence work can proceed. Authorized requeue creates an audited late-repair delivery generation: it never moves that frontier backward and never silently reorders later work. It is available only to consumers that declare idempotent out-of-order repair. Stateful consumers that cannot repair out of order use a new subscription version with deterministic rebuild or an explicit compensation workflow. Selecting an already acknowledged event is a no-op under the original effect idempotency key; a genuinely new compensating effect requires a separately modeled command.

### 7. Transactional outbox guarantees event-to-delivery atomicity, not magical business atomicity

The event row and its pending consumer-delivery rows are committed together. When business state and the event store share a PostgreSQL unit of work, an application service may also commit business state and the event/outbox in that transaction. When they do not share a transactional resource, the contract explicitly reports that limitation and relies on a domain idempotency key and reconciliation.

For Harness, every recoverable transition is appended as the durable decision before the in-memory projection advances: `PLAN`/`EXECUTE`/`VERIFY` phase entry and exit, replan, retry, route-to-repair, wait-for-approval, approval resume/cancel, budget exhaustion, halt, failure, and success. Replay can apply a committed transition after a crash. For workflow execution, checkpoint metadata records the last durable stream sequence and recovery replays subsequent committed events. External side effects are scheduled only after the causal event commits.

Alternatives rejected: two-phase commit across arbitrary tools and external APIs is unavailable; writing an outbox after business commit retains a loss window; claiming exactly-once hides rather than solves retry behavior.

### 8. Replay has separate modes and is side-effect-free by default

The old `replay_to_bus()` behavior is removed from production paths. The runtime exposes:

- `REBUILD_STATE`: apply ordered events to registered pure reducers;
- `VERIFY_HISTORY`: rerun deterministic workflow/Harness decisions and compare generated commands with recorded history;
- `REDELIVER`: an explicit authorized operator action that schedules selected events through the normal delivery ledger.

`REBUILD_STATE` and `VERIFY_HISTORY` never invoke live LLM, Tool, MCP, HTTP, email, publication, memory write, or other external side-effect handlers. Nondeterministic operations are represented as activities whose input reference, output reference, status, version, and idempotency key are recorded; replay consumes the recorded result. Workflow/handler versions are pinned in history and incompatible versions fail with a typed diagnostic until a registered migration or versioned handler is selected.

Replay transactionally captures a finite source high watermark when it starts, reads only through that watermark by stream sequence, validates checksums and schemas, supports a checkpoint plus `after_sequence`, and records a separate replay report without modifying the source stream. Live append after the watermark cannot change or indefinitely extend that replay. `REDELIVER` requires an event/consumer selection, authorization, reason, idempotency readiness, and audit record.

Alternatives rejected: republishing history to the live bus repeats effects; sorting by occurrence timestamp cannot recover the authoritative sequence; rerunning LLM/tool calls cannot reproduce historical decisions.

### 9. Trace propagation uses OpenTelemetry and W3C, not a parallel protocol

`TraceContext` becomes a compatibility facade over a standards-compatible immutable context. HTTP, MCP, Tool, worker, and message boundaries use `extract -> child span -> inject`. Trace IDs are 16 bytes and span IDs are 8 bytes in W3C hexadecimal form; external context is validated and may be restarted at a trust boundary. `tracestate` is not a business metadata container.

OpenTelemetry `Resource` identifies the service/instance and `InstrumentationScope` identifies the emitting library/component. Async fan-out, fan-in, queues, retries, and batch work use span links where one parent cannot represent causality. Trace sampling may omit telemetry, but durable Harness/workflow events are never sampled. Business `run_id`, `workflow_id`, `correlation_id`, and `event_id` remain independent of trace IDs.

The OpenTelemetry API/SDK is optional at framework import time; a no-op tracer preserves runtime behavior. Existing `TraceContext.root()`, `child()`, serialization, and `trace_fields()` callers receive a deprecation window, but newly stored events contain one canonical trace block.

### 10. Security policy runs before storage and before export

Schema definitions classify fields as allowed, reference-only, sensitive, or forbidden. The publisher applies one shared security projector before local or PostgreSQL append, ensuring backend parity. Core identity, sequence, producer, trace, tenant, classification, and checksum fields are infrastructure-owned and cannot be overridden through extensions.

`security_classification` is one of `public`, `internal`, `confidential`, or `restricted`; the default is `internal`. If `tenant_id` is present, reads, exports, dead-letter operations, and replay selection must preserve that scope through the application service. Event/trace identifiers are correlation data, never authentication or authorization credentials.

The redacted `events.jsonl` projection, logs, metrics, delivery errors, and telemetry do not expose raw secrets. Oversized non-sensitive data may use an ordinary integrity-protected artifact reference. Reference-only, confidential, and restricted content fails before append unless a separately composed secure payload store provides tenant authorization, encryption, integrity, and access audit. This change does not treat the current ordinary artifact store as that capability. Integrity checks cover the post-projection canonical record so a stored event cannot later change unnoticed.

### 11. Online queries use the store; JSONL remains a compatible projection

`RunInspectionService` queries an application-owned event reader port. API, CLI, MCP, and SSE retain existing filters and output envelopes while gaining stable sequence and pagination metadata. They do not import a concrete event store.

`run/<run_id>/events.jsonl` remains present for offline review, artifacts, and historical tooling. It is generated from the canonical durable stream, is redacted, uses stable ordering, and records its source high-watermark/checksum in the run manifest. It is not read back to populate the store. If the store is unavailable, online inspection returns an explicit unavailable/stale status; it does not silently present a projection as current authoritative data.

### 12. Compatibility is transitional and deletion is part of the change

Adapters read existing `newsroom.event.v1`, `newsroom.event_envelope.v1`, `newsroom.event_record.v1`, storage JSON records, and legacy run JSONL. Migration maps old 0-based line offsets to 1-based stream sequences and produces a report for conflicts or missing required history. Missing occurrence time, conflicting trace/run fields, duplicate IDs with different content, and unsupported schema versions are quarantined.

During one migration release, public `framework.events` imports, `EventRecorder.emit()`, `write_jsonl()`, `TraceContext.root()/child()`, and callable subscriber registration remain deprecated shims. New production code uses scoped emitters and the durable runtime. After repository callers and migration fixtures are converted, the dual `_records/_envelopes` state, runner-local stores/models/factory, post-run `_index_events()`, legacy mixed subscriber payload, and live-bus replay path are deleted.

Deletion release qualification also requires a signed compatibility gate
separate from rollback qualification. The tracked v4 policy pins three distinct
Git identities: the exact pre-deletion compatibility commit/tree/parent, the
commit/tree/parent at which compatibility code was deleted, and the exact
qualified descendant commit/tree/parent from which the deletion build must be
produced. Treating the deletion boundary as the only eligible later build would
exclude required hardening; allowing an arbitrary descendant would leave the
qualified source mutable.

Authority trust is a separate fail-closed activation boundary. The tracked
policy currently has `authority_trust_status=pending_external_activation`, null
`trust_epoch`, null governance/observer/consumer-owner roots, and checksum
`sha256:383355c7a5382fb47448346a1da8f6c3f38475615042cbab8a5072c128d4eb1f`;
it cannot qualify evidence. A release-security/change-control governance
bootstrap root must already exist in compiled production trust before any
evidence bundle or activation input is accepted. It is independent from the
observer and consumer-owner roots and cannot be selected by policy content,
record D, or a CLI PEM path.

That bootstrap root signs exact bytes of
`newsroom.durable-event-compatibility-trust-activation/v1` record D. D binds the
active policy checksum, a positive `trust_epoch`, mutually independent
governance/observer/consumer-owner roots, a content-addressed verifier build,
its activation deployment ID/environment/time/URI, retained activation
evidence, and governance attestor identity/key/fingerprint/signing time. The
active policy and compiled verifier constants must contain the same
`trust_epoch`, three authority IDs, key IDs, `algorithm=Ed25519` requirements,
fingerprints, and active policy checksum. Pending/null/mismatched trust, a D
signature from any non-bootstrap key, or a verifier build/policy/compiled
mismatch fails before A, B, or C is evaluated.

The activation deployment must precede governance signing, governance signing
must precede A's `observation_window.started_at`, and D's environment must equal
the compatibility and deletion deployment environment. Evidence from a window
that began before D was signed cannot be blessed retroactively. D's activation
evidence retention must extend through C's attestor signing time.

The governance Ed25519 signature authenticates record D but does not itself
provide trusted time. D's retained activation evidence must be anchored in an
independently auditable, non-backfillable deployment or transparency log, or a
trusted timestamp service, binding the verifier build, deployment identity, and
activation time. The offline verifier checks signed digest, URI, retention, and
ordering bindings; external release governance must verify the retained time
anchor before qualification.

The compatibility evidence protocol is a one-way activation plus three-record
release chain so no authority self-selects its own trust root and an owner never
has to approve a deployment that must already exist inside the record being
approved:

```text
pre-existing governance bootstrap root
  -> D newsroom.durable-event-compatibility-trust-activation/v1
    -> A newsroom.durable-event-compatibility-observation/v2
      -> B newsroom.durable-event-compatibility-consumer-signoff/v2
        -> deploy exact B-approved deletion build
          -> C newsroom.durable-event-compatibility-deletion-deployment-attestation/v1
```

D is signed by the bootstrap governance root after the activation deployment.
A is then signed by the activated deployment observer after the bounded
migration-release
window. It binds the compatibility build and deployment, durable query,
checkpoint and projection facts, complete API/CLI/MCP/SDK/SSE inventory, and
content-addressed or retention-locked external evidence; it contains no
deletion deployment. If A uses a retention lock, it must remain valid through
D's `trust_epoch` and record checksum are bound by A, B, and C. B is then signed by an independent
consumer-registry owner and binds A's exact record and inventory checksums plus its
`compatibility_release_digest` and `compatibility_build_digest`. B approves a
known qualified deletion source/build/environment but contains no future
deployment identifier, time, or URI. Only after B exists may that build be
deployed. C is signed after deployment by the trusted deployment observer,
binds A through `observation_record_checksum`, binds B through
`consumer_signoff_record_checksum`, stores the content-addressed or
retention-locked evidence reference in `deployment_evidence`, and proves the
actual deployment fields in `deletion_release` equal B's approved build and
environment plan. A retention lock on `deployment_evidence` must remain valid
beyond C's signing time.

The deterministic verifier requires
`activation.deployed_at <= governance.signed_at < observation.started_at`,
matching activation/compatibility/deletion environments, and
`candidate.deployed_at <= observation.started_at < observation.ended_at <=
observer.signed_at <= consumer_owner.signed_at <= deletion.deployed_at <=
deletion_attestor.signed_at`. It verifies A and C with the observer Ed25519 key,
B with a distinct consumer-owner key, exact-byte detached signatures, canonical
record checksums, authority separation, finite timestamps, exact field sets,
bounded regular files, and content-addressed or retention-locked evidence. Its
CLI accepts D through `--authority-activation` and
`--authority-activation-signature`, the bootstrap public key through
`--trusted-governance-public-key`, and C through `--deletion-attestation` and
`--deletion-attestation-signature`. Governance, observer, and consumer-owner PEM
arguments supply key material only for roots already pinned by compiled
bootstrap trust or the active policy/compiled constants; fingerprints must
match, and neither an evidence bundle nor a CLI caller may select a new trust
root. The verifier never generates trust activation, external observations,
owner decisions, deployment attestations, identities, keys, or signatures.

### 13. Operational signals describe event-runtime health

The runtime emits low-cardinality metrics and structured diagnostics for append latency/failure, pending delivery age/count, retry/dead-letter totals, consumer lag, lease recovery, duplicate IDs, quarantine, schema/upcast results, replay mismatches, export watermark, and storage corruption. Raw payloads and tenant/user values are not metric labels.

Recommended metric families include:

```text
event_append_total{backend,result}
event_append_latency_seconds{backend}
event_delivery_pending{consumer}
event_delivery_lag{consumer}
event_delivery_attempt_total{consumer,outcome}
event_dead_letter_total{consumer,reason_class}
event_schema_validation_total{event_type,result}
event_quarantine_total{reason}
event_replay_total{mode,result}
event_export_high_watermark{projection}
```

Run-owned event retention follows the existing run lifecycle policy. Durable transition events are not compacted independently in this change; payload references keep the stream bounded enough for the first release.

## Risks / Trade-offs

- [The change is broad and crosses active artifact work] -> implement in path-scoped commits, preserve current artifact-path hardening, and do not modify overlapping files until their live diff is reconciled.
- [Dual-write cutover can duplicate events] -> use stable event IDs, a cutover mode, import/live entrypoint separation, and delete post-run indexing before enabling live append by default.
- [Legacy offset conversion is off by one] -> name `legacy_offset`, `stream_sequence`, and `consumer_checkpoint` separately and lock conversion with fixtures.
- [PostgreSQL writers race for a sequence] -> allocate under a stream-row lock or atomic counter in the append transaction; never use `COUNT(*)`.
- [SQLite is mistaken for an HA broker] -> document single-host scope, use conformance tests, and require PostgreSQL for multi-host production.
- [Retries repeat an external effect] -> validate inbox/idempotency integration before activating any external-effect subscription and expose at-least-once semantics in API and docs.
- [A poisoned event blocks its stream] -> bound retries, make DLQ an auditable terminal position in the contiguous frontier, and model requeue as a non-frontier-moving late-repair generation.
- [Schema changes strand historical runs] -> require upcasters and historical fixtures before promotion; quarantine unknown history rather than guessing.
- [Redaction removes data needed for replay] -> fail closed unless a separately authorized and encrypted secure payload store is available; an ordinary artifact reference plus checksum is insufficient.
- [Trace migration breaks existing IDs] -> keep compatibility parsing for historical IDs, generate only W3C-compatible IDs for new work, and never rewrite stored history.
- [Projection and store temporarily disagree] -> include source high-watermark/checksum, surface stale state, and rebuild projection deterministically from the store.
- [Event-store outage blocks critical transitions] -> fail closed before state/external side effects, expose health/readiness, and recover from the last committed checkpoint; never downgrade silently to memory-only.

## Migration Plan

1. Freeze a live inventory of event types, models, readers, writers, and historical JSON fixtures; archive or baseline directly modified completed OpenSpec capabilities.
2. Add canonical models, schema catalog, immutable normalization, security projection, and legacy readers without changing the active write path.
3. Add SQLite/PostgreSQL schema migrations and one conformance suite; backfill historical runs into a staging store and produce conflict/quarantine reports.
4. Introduce the durable runtime behind an explicit configuration flag. Shadow-compare canonical exports with existing JSONL, but do not dispatch twice.
5. Cut Workflow and Harness writers to durable append, generate `events.jsonl` from the stored stream, and disable post-run `_index_events()` in the same release.
6. Enable durable delivery ledgers, inbox/outbox, retry, dead letters, leases, and consumer checkpoints; migrate observational subscribers one by one.
7. Cut run inspection/API/CLI/MCP reads to the application event reader while preserving response compatibility and explicit projection status.
8. Enable deterministic replay and standards-based tracing after stored history and activity-result coverage pass acceptance fixtures.
9. Remove deprecated duplicate models and paths after one compatibility release and a successful migration audit.

Rollback is phase-scoped. Before the write-path cutover, disable the new runtime and retain the untouched legacy source. After cutover, do not return to unpersisted in-memory dispatch; roll back application readers/dispatchers while preserving newly committed canonical events, then replay or export them through the prior compatible projection. Never repair rollback by deleting events, disabling schema checks, or treating quarantine as success.

## Open Questions

None for implementation start. Future broker adapters, cross-region replication, and independent archival/compaction require separate changes after the local/PostgreSQL contract is proven.
