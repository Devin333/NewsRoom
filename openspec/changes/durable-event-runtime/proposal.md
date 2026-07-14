## Why

`framework/events` currently provides useful in-process event models, recording, and notification, but it does not provide one authoritative event contract or durable delivery semantics. Subscriber failure can create partial delivery, event and envelope context can conflict, recorder paths disagree about what was recorded, replay can repeat external side effects, and the raw workflow event export can persist unredacted payloads; these gaps prevent the Harness transcript from serving as a trustworthy replay and review boundary.

## What Changes

- Introduce one canonical, deeply immutable event contract with a stable event identity, explicit domain schema identity, occurrence/observation timestamps, business correlation/causation fields, and a separate standard trace context.
- Replace caller-managed or timestamp-derived ordering with store-assigned per-stream sequence numbers and consumer checkpoints. The system will not claim a global total order.
- Add a durable event runtime with atomic append, transactional outbox integration, effect-level inbox deduplication, version-scoped contiguous checkpoints, explicit `ACK` / `RETRY` / policy-approved `DROP` outcomes, bounded retry with jitter, dead-letter handling, controlled late repair, and consumer isolation.
- Make replay a dedicated, deterministic mode that rebuilds state through side-effect-free reducers and reads recorded LLM/tool/activity outcomes rather than republishing history to live side-effect subscribers.
- Add an event schema catalog with validation, compatibility policy, upcasters, unknown-version quarantine, and historical fixture tests.
- Adopt OpenTelemetry and W3C Trace Context at process and message boundaries while keeping trace data separate from the durable business event identity and transcript.
- Require policy-driven redaction before every durable event write or export; allow ordinary payload references only for oversized non-sensitive content and fail closed for protected content until a separately authorized and encrypted secure payload store is available.
- **BREAKING**: converge `Event`, `EventEnvelope`, framework `EventRecord`, and storage `EventRecord` onto one canonical stored-envelope representation; remove ambiguous list/record behavior and reject conflicting duplicate context fields.
- **BREAKING**: change workflow event persistence from post-run JSONL indexing to durable append during execution; `events.jsonl` becomes a generated, redacted projection rather than the source of truth.

## Capabilities

### New Capabilities

- `durable-event-contract`: Defines canonical event identity, immutable payloads, schema validation/evolution, time semantics, business correlation, trace separation, serialization, and safe export.
- `durable-event-delivery`: Defines atomic append, per-stream ordering, outbox/inbox, subscriber outcomes, bounded retries, dead letters, checkpoints, backpressure, and consumer isolation.
- `deterministic-event-replay`: Defines replay modes, ordered recovery, side-effect exclusion, activity-result reuse, checkpoint/resume, compatibility checks, and replay diagnostics.
- `event-trace-propagation`: Defines OpenTelemetry/W3C propagation, resource and instrumentation ownership, span links, sampling boundaries, and trace-to-event correlation.

### Modified Capabilities

- `workflow-storage-indexing`: Workflow events become durable during execution and `events.jsonl` becomes a redacted export projection of the stored stream rather than an input that is indexed after run completion.

## Impact

- Core runtime: `framework/events`, Harness and workflow event bridges, recorders, replay paths, and trace helpers.
- Storage: `infrastructure/storage/events`, PostgreSQL event storage, transactional workflow persistence, migrations, redaction, consumer state, and dead-letter records.
- Interfaces: run inspection, event query/export, API/CLI/MCP diagnostics, and operator replay/dead-letter controls through application services.
- Tests: event contracts, storage conformance, failure injection, crash recovery, schema fixtures, replay determinism, trace propagation, architecture boundaries, and workflow integration.
- Compatibility: existing historical `newsroom.event*` and workflow JSONL records require explicit import/upcasting; unknown or ambiguous records are quarantined rather than silently assigned current timestamps or context.
- Dependencies: OpenTelemetry API/SDK integration remains optional at framework import time; the first production store uses existing local/PostgreSQL infrastructure and does not require Kafka, Temporal, or Dapr.
