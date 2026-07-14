## ADDED Requirements

### Requirement: Durable append commits before subscriber visibility
The system SHALL atomically commit the canonical event, its per-stream sequence, and pending delivery work before any asynchronous consumer can observe the event.

#### Scenario: Event append commits successfully
- **WHEN** a valid event is published
- **THEN** the store assigns observation time and stream sequence, computes the complete-record checksum, and commits the event and delivery work in one backend transaction
- **AND** dispatch begins only after that commit

#### Scenario: Storage fails before commit
- **WHEN** sequence allocation, event append, outbox creation, or commit fails
- **THEN** no subscriber observes the event
- **AND** no partial event or pending delivery work remains visible

### Requirement: Ordering is guaranteed only within a stream
The system SHALL assign a unique 1-based monotonically increasing `stream_sequence` atomically within each `stream_id` and SHALL NOT advertise a total order across independent streams.

#### Scenario: Concurrent writers append to one stream
- **WHEN** multiple writers append to the same stream concurrently
- **THEN** each accepted event receives a distinct monotonic sequence
- **AND** readers observe that stream in sequence order

#### Scenario: Writers append to different streams
- **WHEN** events are appended to different streams concurrently
- **THEN** each stream preserves its own order
- **AND** no cross-stream order is inferred from timestamps or sequence values

### Requirement: Local and PostgreSQL backends implement one conformance contract
The system SHALL provide a transactional SQLite backend for local single-host use and a PostgreSQL backend for shared production use, selected through the storage event-store factory and verified by the same conformance suite.

#### Scenario: No database DSN is configured
- **WHEN** the runtime is composed without `NEWS_DATABASE_DSN`
- **THEN** the factory creates the configured local SQLite event backend
- **AND** workflow production paths use that backend rather than a runner-local JSON store

#### Scenario: PostgreSQL DSN is configured
- **WHEN** the runtime is composed with `NEWS_DATABASE_DSN`
- **THEN** the factory creates the PostgreSQL event backend
- **AND** stream sequence allocation and complete-record checksum generation occur atomically in the append transaction without `COUNT(*)`

#### Scenario: Backend conformance is tested
- **WHEN** the storage conformance suite runs against SQLite and PostgreSQL adapters
- **THEN** append, identity, ordering, pagination, outbox, inbox, checkpoint, retry, dead-letter, rollback, and recovery semantics match

### Requirement: Delivery semantics are explicitly at-least-once
The system SHALL expose at-least-once delivery and SHALL require every consumer to have a stable `consumer_id` and return `ACK`, `RETRY`, or `DROP` with a bounded diagnostic reason.

#### Scenario: Consumer acknowledges an event
- **WHEN** a consumer completes its effect and returns `ACK`
- **THEN** the inbox records terminal success and its checkpoint may advance

#### Scenario: Consumer requests another attempt
- **WHEN** a consumer returns `RETRY` or raises a retryable error
- **THEN** the delivery ledger schedules a bounded later attempt
- **AND** does not mutate the canonical event

#### Scenario: Consumer intentionally drops an event
- **WHEN** a consumer returns `DROP` for a deterministic, policy-approved non-error skip
- **THEN** the terminal skip is recorded and auditable
- **AND** the stream can advance for that consumer

#### Scenario: Consumer encounters a permanent processing failure
- **WHEN** deterministic error classification marks processing as permanently failed rather than intentionally skipped
- **THEN** the delivery enters the durable dead-letter state without consuming further retry budget
- **AND** the consumer cannot use `DROP` to bypass dead-letter diagnostics or operator controls

### Requirement: Consumer subscriptions have explicit durable start semantics
The system SHALL persist a versioned consumer subscription with deterministic event/schema filters and an explicit `EARLIEST`, `LATEST`, or `AT_SEQUENCE` start policy, and SHALL reconcile registration with concurrent publication without silent gaps or duplicate delivery rows.

#### Scenario: New consumer starts from earliest history
- **WHEN** a consumer registers with `EARLIEST`
- **THEN** the runtime creates delivery work for every matching retained event from the first available sequence
- **AND** continues with matching events committed during registration without skipping the boundary

#### Scenario: New consumer starts from the current end
- **WHEN** a consumer registers with `LATEST`
- **THEN** its durable start watermark is fixed transactionally
- **AND** only matching events committed after that watermark become delivery work

#### Scenario: Consumer starts at a requested sequence
- **WHEN** a consumer registers with `AT_SEQUENCE` and a valid retained sequence
- **THEN** matching delivery begins at the explicitly documented inclusive sequence
- **AND** invalid or no-longer-retained positions fail with a typed error

#### Scenario: Subscription is paused and resumed
- **WHEN** an operator pauses a subscription
- **THEN** matching committed events continue to receive durable delivery rows while new claims stop
- **AND** resume claims the accumulated rows from the unchanged contiguous frontier without a registration gap

#### Scenario: Subscription is retired
- **WHEN** an operator retires a subscription
- **THEN** the runtime transactionally fixes a retirement watermark and creates no delivery rows for later events
- **AND** retirement completes only after existing nonterminal rows drain or an authorized terminal-cancellation disposition records each remaining row

#### Scenario: Subscription definition changes
- **WHEN** an operator changes a filter or start position
- **THEN** the runtime creates a new subscription version with independent deliveries and checkpoints
- **AND** it does not rewrite the prior version's progress, attempts, or audit history

### Requirement: Consumer effects are idempotent
The system SHALL require each subscription to declare whether it performs external effects and a stable `consumer_effect_id`. Before an external-effect subscription becomes active or receives its first delivery, the system SHALL validate an inbox uniqueness boundary for `(event_id, consumer_effect_id)` or an equivalent idempotency contract coupled to the effect.

#### Scenario: Worker crashes after effect but before response
- **WHEN** an external effect succeeds but the worker crashes before the runtime records the response
- **THEN** a redelivery uses the same event and consumer idempotency key
- **AND** the consumer does not apply the business effect twice

#### Scenario: Consumer cannot provide idempotency
- **WHEN** an external-effect consumer cannot demonstrate a valid idempotency boundary
- **THEN** the runtime refuses to activate or deliver to that subscription
- **AND** operator authorization cannot turn automatic retry, lease recovery, requeue, or redelivery into an unsafe non-idempotent effect

### Requirement: Consumer failure is isolated
The system SHALL isolate consumer progress so that one failing consumer does not prevent other consumers from handling the same committed event.

#### Scenario: One of three consumers fails
- **WHEN** two consumers acknowledge and one consumer requests retry
- **THEN** the successful consumers remain terminally acknowledged
- **AND** only the failing consumer receives another attempt

#### Scenario: Observational consumer fails during workflow execution
- **WHEN** a noncritical audit, export, or telemetry consumer fails
- **THEN** the failure is recorded in its delivery ledger
- **AND** it does not roll back an already committed workflow event or cause deterministic workflow work to be repeated

### Requirement: Retry is bounded and dead letters are durable
The system SHALL apply a configurable bounded retry policy with exponential delay, cap, and jitter and SHALL create a durable dead-letter record after exhaustion or permanent failure.

#### Scenario: Retry succeeds within budget
- **WHEN** a consumer succeeds before the configured attempt limit
- **THEN** the delivery becomes acknowledged and no dead-letter record is created

#### Scenario: Retry budget is exhausted
- **WHEN** a consumer remains retryable through the final allowed attempt
- **THEN** the delivery moves to the dead-letter state
- **AND** records event id, consumer id, attempt count, first and last failure times, reason class, and redacted diagnostics

#### Scenario: Dead-letter record is inspected
- **WHEN** an operator lists a dead-letter entry
- **THEN** the response contains no unredacted event payload, credentials, or arbitrary exception dump

### Requirement: Dead-letter operations are controlled and auditable
The system SHALL expose application-service operations to inspect, requeue, or terminally resolve dead letters with authorization, tenant scope, reason, and audit records.

#### Scenario: Authorized operator requeues a dead letter
- **WHEN** an authorized operator provides the target consumer, reason, and idempotency readiness
- **THEN** the runtime schedules a new delivery generation without changing the original event
- **AND** records the operator action while preserving the original dead-letter and delivery history

#### Scenario: Dead letter is requeued after the normal frontier advanced
- **WHEN** an authorized requeue targets sequence N after later sequences have terminal dispositions
- **THEN** the runtime treats it as a separate late-repair generation and does not move the normal checkpoint backward or reorder or block later events
- **AND** it permits the operation only for a consumer contract that supports idempotent out-of-order repair; otherwise it requires a new subscription version plus deterministic rebuild or a separate compensating workflow

#### Scenario: Previously acknowledged effect is selected for redelivery
- **WHEN** redelivery selects an event whose effect inbox is already terminally successful
- **THEN** the normal consumer effect remains a no-op under the original idempotency key
- **AND** intentionally applying a new compensating effect requires a separately modeled and authorized compensation command rather than bypassing the inbox

#### Scenario: Interface calls dead-letter operation
- **WHEN** API, CLI, or MCP requests a dead-letter action
- **THEN** the interface calls an application service rather than a concrete store or dispatcher

### Requirement: Consumer checkpoints are durable and unambiguous
The system SHALL persist a highest contiguous terminal frontier per `(subscription_id, subscription_version, stream_id)` and SHALL distinguish it from consumer effect identity, legacy line offsets, delivery attempt numbers, and late-repair generations. A frontier at N means every matching delivery at or below N has an auditable terminal disposition and no lower matching delivery remains pending, claimed, or waiting for retry.

#### Scenario: Consumer restarts
- **WHEN** a consumer process resumes after failure
- **THEN** it continues after its subscription version's contiguous terminal frontier
- **AND** recovers claimed but unacknowledged deliveries through the lease policy

#### Scenario: Earlier delivery waits for retry
- **WHEN** sequence N is nonterminal and a later matching sequence N+1 exists for the same subscription version and stream
- **THEN** N+1 is not claimed as normal ordered work and the checkpoint cannot advance past N
- **AND** normal delivery concurrency is permitted across different streams but not across unresolved matching sequences in one stream

#### Scenario: A dead-letter creates a sequence gap
- **WHEN** a stream event reaches a terminal dead-letter state
- **THEN** the terminal disposition closes that position and allows the contiguous frontier to advance so later events are not blocked indefinitely
- **AND** inspection exposes the gap

### Requirement: Delivery claims use bounded leases
The system SHALL claim delivery work with a lease owner and expiry so crashed workers cannot hold work permanently and active workers cannot process the same claim concurrently without recovery semantics.

#### Scenario: Dispatcher dies with an active claim
- **WHEN** a lease expires without a terminal outcome
- **THEN** another dispatcher can recover the delivery and increment its attempt safely

#### Scenario: Stale worker responds after lease loss
- **WHEN** a worker tries to acknowledge a claim generation it no longer owns
- **THEN** the runtime rejects the stale acknowledgement

### Requirement: Backpressure is bounded per consumer
The system SHALL impose configurable batch size, in-flight count, and concurrency limits per consumer and SHALL expose lag and oldest-pending-age diagnostics.

#### Scenario: Consumer is slower than producers
- **WHEN** pending work exceeds the consumer's in-flight limit
- **THEN** the dispatcher does not claim unlimited additional work
- **AND** metrics expose pending count, lag, and oldest pending age

#### Scenario: Durable capacity is unavailable
- **WHEN** admission or durable storage capacity cannot accept another event
- **THEN** publication fails before commit with a typed availability or capacity error
- **AND** never degrades silently to memory-only delivery

### Requirement: Business state atomicity is declared, not assumed
The system SHALL atomically commit business state and event/outbox only when they share an explicit unit of work and SHALL expose reconciliation requirements otherwise.

#### Scenario: PostgreSQL application service shares the event transaction
- **WHEN** business state and an event are written through the same PostgreSQL unit of work
- **THEN** both commit or both roll back

#### Scenario: External system cannot join the event transaction
- **WHEN** an effect targets an external API, tool, or independent database
- **THEN** the runtime uses at-least-once delivery and an idempotency key
- **AND** does not claim end-to-end exactly-once behavior

### Requirement: Event runtime health is observable without payload leakage
The system SHALL expose low-cardinality append, delivery, retry, dead-letter, lag, lease, duplicate, quarantine, and storage-health telemetry without raw payload, tenant, user, run, event, or trace values as metric labels.

#### Scenario: Delivery retry is recorded
- **WHEN** a consumer schedules a retry
- **THEN** structured diagnostics and counters identify the consumer and outcome class
- **AND** exclude raw event contents and secret-bearing exception values
