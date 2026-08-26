## ADDED Requirements

### Requirement: Runtime facts use one canonical durable stream

Turn, tool, approval, compaction, child-agent, worker-heartbeat, timeout, cancellation, indeterminate, and terminal outcome facts SHALL be emitted through one canonical runtime event publisher before they are exposed by projection or operator APIs.

#### Scenario: Tool fact reaches operator timeline

- **WHEN** a controlled tool invocation starts and completes
- **THEN** the publisher SHALL persist start/observation facts with stable scope, sequence, checksum, and redaction metadata
- **AND** projection/API SHALL derive its status from those durable facts

#### Scenario: Module writes projection directly

- **WHEN** a worker or interface attempts to mutate the operator projection without publishing a canonical event
- **THEN** the write SHALL be rejected
- **AND** no operator state transition SHALL be accepted from the direct projection write

### Requirement: Event identity and redaction are durable

Each canonical event SHALL bind event id, run/parent/child scope, Graph identity, node/attempt identity where applicable, a durable-store-assigned per-run monotonic sequence, occurrence time, payload checksum, schema version, and redaction metadata. The durable store SHALL enforce `(run_id, sequence)` uniqueness and event-id/checksum idempotency; a same-id different-payload or concurrent sequence conflict SHALL return a typed conflict without overwriting the original event. Secrets, private context, raw prompts, and unbounded payloads SHALL be rejected or replaced with bounded references before persistence.

#### Scenario: Event is safely persisted

- **WHEN** an event contains valid identity, schema, bounded payload, and redaction evidence
- **THEN** the durable event runtime SHALL persist it once and return a verifiable receipt
- **AND** projection SHALL be able to rebuild the same state from the receipt

#### Scenario: Event contains a secret-like value

- **WHEN** an event payload or nested metadata contains a secret-like value or forbidden private field
- **THEN** canonical publication SHALL fail closed or apply the approved redaction transform
- **AND** the raw value SHALL not appear in durable event, projection, API response, or metric payload

#### Scenario: Concurrent publishers contend for a sequence

- **WHEN** two publishers append events for one run concurrently
- **THEN** the durable store SHALL atomically assign a unique per-run sequence or return a typed retry/conflict outcome
- **AND** projection SHALL never expose two different payloads for the same `(run_id, sequence)`

### Requirement: Projection and API support cursor reconnect

The runtime projection and operator read service SHALL support bounded, run-scoped cursors based on durable event sequence. A cursor SHALL encode schema version, run/Graph scope, last sequence, and an authorization principal/tenant fingerprint. The read service SHALL authenticate and authorize the principal against the run before resolving the cursor, SHALL persist projection checkpoints, and SHALL return only redacted bounded references. Rebuild, duplicate delivery, reconnect, and cross-run queries SHALL be deterministic and idempotent.

#### Scenario: Operator reconnects after a cursor

- **WHEN** an operator requests events for a run with `after_cursor=c1`
- **THEN** the read service SHALL return only later events in stable sequence order within the same run
- **AND** repeated delivery of an already applied event SHALL not change the projection

#### Scenario: Cursor crosses run scope

- **WHEN** a cursor or event reference belongs to another run or Graph identity
- **THEN** the operator read service SHALL reject it with a typed scope error
- **AND** it SHALL not disclose the other run's events

#### Scenario: Principal is not authorized for a run

- **WHEN** an authenticated principal presents a validly shaped cursor for a run outside its tenant or ownership scope
- **THEN** the read service SHALL reject the request before reading event payloads
- **AND** it SHALL record a bounded authorization audit fact without disclosing whether the run exists

### Requirement: Runtime events preserve control-plane authority

Canonical event publication SHALL record observations and decisions but SHALL NOT grant routing, approval, tool authorization, memory write, side-effect, or publication authority to workers or operator readers.

#### Scenario: Worker emits a route-shaped event

- **WHEN** an LLM or worker emits a candidate event containing next-node or quality-verdict data
- **THEN** the event SHALL be stored as an observation only
- **AND** Harness SHALL choose routing and verdict from deterministic control-plane evidence

#### Scenario: Operator reads an approval event

- **WHEN** an operator reads a pending or decided approval event
- **THEN** the API SHALL expose bounded read-only approval context
- **AND** only the approved Harness resume path SHALL be able to commit the resulting control transition

### Requirement: Approval decisions use the Harness write path

Approval requested, decided, rejected, and expired facts SHALL be persisted through the Harness approval application service using a deterministic authorizer, approval scope/Graph Wait identity, idempotency key, authoritative receipt, and canonical event outbox. Operator readers and workers SHALL have no direct approval-decision write capability.

#### Scenario: Approval decision is committed

- **WHEN** an authorized principal submits a decision for the current Graph Wait
- **THEN** the approval service SHALL validate scope and idempotency, commit the decision receipt, and enqueue the canonical decision event
- **AND** Harness SHALL be the only component allowed to resume the Wait

#### Scenario: Duplicate approval decision is replayed

- **WHEN** the same decision identity and payload checksum are submitted again
- **THEN** the service SHALL return the original receipt without creating a second resume or event
- **AND** a conflicting decision body SHALL fail without changing the original decision
