## ADDED Requirements

### Requirement: Harness owns bounded child-agent lifecycle
The Harness SHALL expose `spawn`, `status`, `wait`, `cancel`, and `close` operations for child agents through a supervisor, and SHALL enforce Graph budgets, allowed tools, memory namespaces, and exact parent/child identity at spawn.

#### Scenario: Spawn requires admission
- **WHEN** a caller requests a child agent without a valid parent Graph identity, allowed capability set, or remaining budget
- **THEN** the supervisor rejects the request before creating a child runtime

#### Scenario: Child cannot own control decisions
- **WHEN** a child returns routing, quality, publication, memory-write, skill-promotion, or sibling-control fields
- **THEN** the supervisor rejects the candidate output and records a boundary violation

### Requirement: Child status is durable and lease-bound
The supervisor SHALL persist lifecycle transitions and heartbeat/lease facts with child identity, and SHALL mark a child `LOST` or reclaimable when its lease expires without a confirmed terminal result.

#### Scenario: Heartbeat keeps a child active
- **WHEN** a child heartbeat matches its current handle and lease
- **THEN** the supervisor extends the lease and emits an idempotent heartbeat event

#### Scenario: Stale lease is reclaimed by Harness
- **WHEN** a child lease expires and no terminal receipt has been committed
- **THEN** the supervisor marks the child `LOST` or enters a bounded reclaim flow; the child cannot self-assign a replacement

### Requirement: Child lifecycle operations are idempotent
Repeated `status`, `wait`, `cancel`, and `close` operations with the same operation identity SHALL return the same durable outcome or a typed conflict, and SHALL not create duplicate child side effects.

#### Scenario: Repeated cancel is safe
- **WHEN** an operator submits the same cancellation twice
- **THEN** the second request returns the committed cancellation outcome without issuing a second cancellation side effect

#### Scenario: Close after terminal state is safe
- **WHEN** `close` is requested for a child already in `SUCCEEDED`, `FAILED`, `CANCELLED`, or `LOST`
- **THEN** the supervisor records or returns an idempotent closed outcome without rerunning the child

### Requirement: Parent restart recovers child state without duplicate execution
After a parent process restart, the supervisor SHALL recover child handles from canonical durable events and transcript evidence before deciding whether to reattach, wait, cancel, reclaim, or fail closed.

#### Scenario: Committed result is reused
- **WHEN** a child has a committed terminal result before the parent restarts
- **THEN** recovery reuses the result and does not spawn a second child attempt

#### Scenario: Ambiguous child remains bounded
- **WHEN** recovery finds a child with no terminal result and no confirmed process ownership
- **THEN** recovery marks the child `LOST` or `indeterminate` and prevents automatic side-effect replay
