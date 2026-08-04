## ADDED Requirements

### Requirement: External side-effect retries fail closed
The runtime SHALL apply one deterministic retry-safety rule to timeout and ordinary-failure outcomes. Operations with no side effect or read-only behavior MAY retry within the shared budget. Operations that can write external state SHALL NOT retry unless their definition explicitly declares both idempotent execution and reconciliation support. An external-write outcome whose completion is uncertain SHALL be terminal and marked indeterminate.

#### Scenario: External write raises after accepting work
- **WHEN** an external-write operation raises an ordinary exception without an idempotency and reconciliation contract
- **THEN** the runtime executes the logical operation once, returns a terminal indeterminate result, and does not retry it

#### Scenario: Safe operation retries
- **WHEN** a read-only operation fails and the shared budget has a remaining permit
- **THEN** the runtime may retry with the same logical-operation key and a new attempt ID

#### Scenario: Deterministic precondition failure occurs before any effect
- **WHEN** an external-write Tool raises an error type declared in its `no_effect_error_types` contract
- **THEN** the runtime preserves the original error, does not retry, and does not mark the outcome indeterminate

### Requirement: Nested logical operations have stable distinct identities
The runtime SHALL derive each nested logical-operation key from the parent key, child kind, and stable child identifier. Sibling logical operations SHALL have distinct keys, and retries of one logical operation SHALL reuse its key.

#### Scenario: Sibling Tool calls
- **WHEN** two Tool calls execute under the same Workflow attempt
- **THEN** they receive different idempotency keys even if they share the same parent context

#### Scenario: Retry of one Tool call
- **WHEN** one Tool call is retried
- **THEN** every attempt uses the same Tool-call idempotency key and a distinct attempt ID

### Requirement: Write fencing is issued by the protected resource
`DataBuffer` SHALL atomically issue a monotonically increasing lease bound to the unique owner of each step attempt. A buffer overlay SHALL write or commit only while both its lease generation and owner match the current resource lease. Caller-provided budget generations SHALL NOT establish write ownership.

#### Scenario: Independent controllers request the same local generation
- **WHEN** two independently budgeted attempts begin writes for the same step
- **THEN** `DataBuffer` issues different ordered leases and rejects writes or commits from the superseded owner

#### Scenario: Stale owner commits after replacement
- **WHEN** a newer owner acquires the step lease before an older overlay commits
- **THEN** the older overlay raises `StaleWorkflowAttemptError` and publishes no staged values

### Requirement: Nested attempts share one fixed total budget
Workflow, worker, parallel-branch, and Tool attempts that belong to one outer operation SHALL share one `AttemptBudget` with a fixed ceiling selected at the outer boundary. Every retry SHALL claim a remaining permit, and nested runtimes SHALL NOT expand the ceiling after execution begins.

#### Scenario: Parallel branch retries
- **WHEN** parallel branches have local retry policies under one Workflow attempt
- **THEN** every branch retry consumes the same parent budget and total executed attempts do not exceed its ceiling

#### Scenario: Nested Tool retry exhausts total budget
- **WHEN** a nested Tool consumes the last permitted attempt
- **THEN** neither the Tool nor its parent step starts an additional retry

### Requirement: Live attempt execution is capacity bounded
`AttemptSupervisor` SHALL acquire shared capacity before starting attempt work and SHALL release that capacity only after the underlying work exits. When capacity is exhausted, the supervisor SHALL return a typed terminal failure without creating another attempt thread.

#### Scenario: Non-cooperative timed-out work fills capacity
- **WHEN** timed-out functions ignore cancellation and occupy every configured attempt slot
- **THEN** a subsequent supervised attempt fails with capacity exhaustion and the number of live attempt threads does not exceed the configured limit

#### Scenario: Timed-out work eventually exits
- **WHEN** a previously unconfirmed function exits
- **THEN** its capacity slot is released and a subsequent attempt may start

### Requirement: Indeterminate descendants cannot publish normal output
An outer attempt SHALL NOT commit staged Workflow data or publish normal business artifacts after any descendant is marked indeterminate. The runtime SHALL retain diagnostic metadata through error envelopes or events without representing it as a successful artifact.

#### Scenario: Parallel branch remains unconfirmed
- **WHEN** a parallel branch times out and remains alive beyond cancellation grace
- **THEN** the parent result is indeterminate and no branch-result artifact is published

#### Scenario: Late Workflow buffer write
- **WHEN** a superseded attempt writes or commits after timeout
- **THEN** `DataBuffer` rejects the operation and the visible snapshot remains unchanged
