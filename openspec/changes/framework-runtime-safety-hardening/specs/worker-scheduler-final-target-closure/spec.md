## ADDED Requirements

### Requirement: Redis task leases are renewable and fenced
Every Redis-backed leased task SHALL have persisted owner, lease id, monotonically increasing fencing token, monotonically increasing attempt number, server-time expiry, and state. Active workers SHALL renew a task lease before expiry, and reclaim SHALL use lease expiry rather than consumer-group idle time as the ownership authority.

#### Scenario: Handler runs longer than the reclaim threshold
- **WHEN** the owning worker continues renewing the task lease while a handler is active
- **THEN** another worker cannot reclaim or execute that stream entry

#### Scenario: Owner stops renewing
- **WHEN** a task lease expires after the worker stops or loses ownership
- **THEN** one reclaimer may establish a new lease with a greater fencing token and attempt number
- **AND** the original immutable stream payload does not reset those counters

### Requirement: Task terminal transitions verify lease ownership atomically
Renew, acknowledge, retry, and dead-letter transitions SHALL atomically compare queue, group, message id, owner, lease id, and fencing token before modifying queue state.

#### Scenario: Stale owner acknowledges after reclaim
- **WHEN** the original worker completes after another worker obtained a newer fencing token
- **THEN** the stale acknowledgement is rejected with a typed lease error
- **AND** it does not acknowledge, retry, dead-letter, or overwrite the current delivery

#### Scenario: Current owner completes successfully
- **WHEN** owner and lease identity match the current ledger
- **THEN** the stream entry is acknowledged and lease state becomes terminal in one atomic operation

### Requirement: Retry and dead-letter transitions preserve monotonic attempts
Redis retry and reclaim SHALL persist the authoritative attempt count outside the original stream payload and SHALL atomically acknowledge the old entry while publishing exactly one next retry or dead-letter record.

#### Scenario: Task crashes and is reclaimed repeatedly
- **WHEN** each lease expires before successful completion
- **THEN** every delivery observes a strictly greater attempt number
- **AND** the task reaches configured retry exhaustion and DLQ rather than resetting to attempt one

#### Scenario: Failure transition is retried after an uncertain client response
- **WHEN** the current owner repeats the same fenced terminal transition
- **THEN** the queue returns the prior terminal result or a typed stale/complete outcome
- **AND** does not create another retry or DLQ entry

### Requirement: Worker execution exposes idempotency and fencing context
The worker runtime SHALL expose the stable task effect key, current lease id, fencing token, attempt, and cancellation state to production handlers and SHALL fail closed on lease-renewal loss before performing further cooperative work.

#### Scenario: Production handler begins work
- **WHEN** a Redis task is dispatched to a handler
- **THEN** the handler can obtain stable idempotency and current fencing data without reading mutable queue internals

#### Scenario: Lease renewal is rejected during work
- **WHEN** the worker no longer owns the task lease
- **THEN** its execution context is cancelled and its terminal queue operation is rejected
