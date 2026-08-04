# attempt-execution-integrity Specification

## Purpose
Define fail-closed retry, identity, resource fencing, capacity, and publication
integrity requirements for nested attempt execution.
## Requirements
### Requirement: External side-effect retries fail closed
The runtime SHALL apply one deterministic retry-safety rule to timeout and ordinary-failure outcomes before consulting retry budgets. Operations with no side effect or read-only behavior MAY retry when local policy, root retry credits, deadline admission, and capacity all allow. Operations that can write external state SHALL NOT retry unless their definition explicitly declares both idempotent execution and reconciliation support. An external-write outcome whose completion is uncertain SHALL be terminal and marked indeterminate.

#### Scenario: External write raises after accepting work
- **WHEN** an external-write operation raises an ordinary exception without an idempotency and reconciliation contract
- **THEN** the runtime executes the logical operation once, returns a terminal indeterminate result, and does not retry it even when budgets remain

#### Scenario: Safe operation retries
- **WHEN** a read-only operation fails, its local budget and root retry credit remain, and deadline/capacity admission succeeds
- **THEN** the runtime may retry with the same logical-operation key, a new physical attempt ID, and the next local attempt number

#### Scenario: Deterministic precondition failure occurs before any effect
- **WHEN** an external-write Tool raises an error type declared in its `no_effect_error_types` contract
- **THEN** the runtime preserves the original error, does not retry unless all new admission gates also pass, and does not mark the outcome indeterminate

### Requirement: Nested logical operations have stable distinct identities
The runtime SHALL derive each nested logical-operation key from the parent key, child kind, and stable child identifier. Sibling logical operations SHALL have distinct keys, and retries of one logical operation SHALL reuse its key. Each logical operation SHALL own a `LocalRetryBudget`; a root-scoped `RetryCreditLedger` MAY limit the total number of retries but SHALL NOT replace local attempt numbering or resource ownership.

#### Scenario: Sibling Tool calls
- **WHEN** two Tool calls execute under the same Workflow attempt
- **THEN** they receive different idempotency keys, independent local attempt counters, and no shared attempt/fence sequence even if they share the same parent context

#### Scenario: Retry of one Tool call
- **WHEN** one Tool call is retried
- **THEN** every attempt uses the same Tool-call idempotency key, a distinct attempt ID, and an incremented local attempt number while its parent Step number remains unchanged

### Requirement: Write fencing is issued by the protected resource
`DataBuffer` SHALL atomically issue a monotonically increasing lease bound to the unique owner of each step attempt. A buffer overlay SHALL write or commit only while both its lease generation and owner match the current resource lease. Caller-provided budget generations, retry credits, or generic attempt sequences SHALL NOT establish write ownership.

#### Scenario: Independent controllers request the same local generation
- **WHEN** two independently budgeted attempts begin writes for the same step
- **THEN** `DataBuffer` issues different ordered resource leases and rejects writes or commits from the superseded owner, regardless of either attempt's local number or retry credit

#### Scenario: Stale owner commits after replacement
- **WHEN** a newer owner acquires the step lease before an older overlay commits
- **THEN** the older overlay raises `StaleWorkflowAttemptError` and publishes no staged values

### Requirement: Live attempt execution is capacity bounded
`AttemptSupervisor` SHALL perform deadline, cancellation, retry-safety, and budget admission before creating attempt work, acquire shared capacity before starting admitted work, and release that capacity only after the underlying work exits. When capacity is exhausted, the supervisor SHALL return a typed no-start rejection without creating another attempt thread or consuming a local slot/root retry credit.

#### Scenario: Non-cooperative timed-out work fills capacity
- **WHEN** timed-out functions ignore cancellation and occupy every configured attempt slot
- **THEN** a subsequent supervised attempt fails with `attempt_capacity_exhausted`, the number of live attempt threads does not exceed the configured limit, and no retry credit is consumed by the rejected request

#### Scenario: Timed-out work eventually exits
- **WHEN** a previously unconfirmed function exits
- **THEN** its capacity slot is released and a subsequent admitted attempt may start with a new physical attempt ID and its own local number

### Requirement: Indeterminate descendants cannot publish normal output
An outer attempt SHALL NOT commit staged Workflow data or publish normal business artifacts after any descendant is marked indeterminate. The runtime SHALL retain diagnostic metadata through error envelopes or events without representing it as a successful artifact, and remaining local/root retry budget SHALL not override this gate.

#### Scenario: Parallel branch remains unconfirmed
- **WHEN** a parallel branch times out and remains alive beyond cancellation grace
- **THEN** the parent result is indeterminate, no branch-result artifact is published, and no parent retry is admitted solely because budget remains

#### Scenario: Late Workflow buffer write
- **WHEN** a superseded attempt writes or commits after timeout
- **THEN** `DataBuffer` rejects the operation and the visible snapshot remains unchanged
