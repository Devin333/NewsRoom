## ADDED Requirements

### Requirement: Supervisor owns production child lifecycle

All production child-agent dispatch SHALL be performed through `ChildAgentSupervisor`. Existing child worker implementations MAY be used as execution adapters, but no parallel `SubAgentRuntime` or interface service SHALL independently own spawn, heartbeat, cancellation, close, terminal state, or recovery. The supervisor's launch and terminate adapters SHALL use the admitted `ExecutionEnvironment` and SHALL persist a durable execution receipt, child lease, and attempt binding.

#### Scenario: Child dispatch is admitted

- **WHEN** Harness schedules a child-agent activity
- **THEN** the supervisor SHALL create the parent/child/lease/attempt identity before invoking the worker
- **AND** the worker SHALL NOT choose its own routing, authorization, retry, or terminal status

#### Scenario: Child provider is unavailable

- **WHEN** the child launch adapter cannot resolve a provider capable of the requested profile and capabilities
- **THEN** supervisor SHALL reject `spawn` with a typed execution-capability denial
- **AND** it SHALL not start a host-process child as a fallback

#### Scenario: Bypass child owner is found

- **WHEN** a production caller constructs an independent child runtime or directly invokes a child process
- **THEN** the integration gate SHALL fail
- **AND** the caller SHALL be migrated to the supervisor or documented as an out-of-scope non-production utility

### Requirement: Child lifecycle operations are durable and idempotent

`spawn`, `status`, `wait`, `heartbeat`, `cancel`, and `close` SHALL use stable parent/child/lease/attempt identity, durable receipts/events, and identical-body idempotency. Conflicting requests for the same identity SHALL fail without overwriting the original lifecycle fact.

#### Scenario: Duplicate close is replayed

- **WHEN** the same authorized `close` request is submitted twice with the same identity and payload checksum
- **THEN** both calls SHALL return the original terminal receipt
- **AND** only one terminal side effect and one canonical lifecycle fact SHALL be committed

#### Scenario: Conflicting lifecycle request arrives

- **WHEN** a request reuses a child identity with a different lease, attempt, or payload checksum
- **THEN** the supervisor SHALL return a typed conflict
- **AND** the existing child receipt and terminal state SHALL remain unchanged

### Requirement: Child state has a durable backing port

The production supervisor SHALL receive durable lease, heartbeat, execution-receipt, transcript/output-reference, and idempotency repositories through the composition boundary. In-memory repositories MAY be used by contract tests only and SHALL be rejected by production qualification.

#### Scenario: Parent restarts with an active lease

- **WHEN** a new supervisor process starts for a parent run with a previously committed child lease
- **THEN** it SHALL load the lease and latest heartbeat from the durable repositories
- **AND** it SHALL classify the child before issuing a new worker call

#### Scenario: Production uses an in-memory child store

- **WHEN** composition resolves an in-memory child lease or receipt repository for a production profile
- **THEN** startup/admission SHALL return a typed durability-blocked result
- **AND** no child activity SHALL be accepted as production-ready

### Requirement: Restart recovery classifies uncertainty

After parent process restart, the supervisor SHALL recover child state from durable lease, heartbeat, transcript/output receipt, and canonical event evidence. It SHALL distinguish completed, resumable, lost, indeterminate-cancel, and manual-repair states before any worker invocation.

#### Scenario: Child completed before parent crash

- **WHEN** a valid child result and terminal receipt exist before restart
- **THEN** recovery SHALL return the recorded result without invoking the child worker
- **AND** Harness SHALL continue from the recorded deterministic evidence

#### Scenario: Child has no terminal evidence

- **WHEN** a lease is present but the child has no valid terminal receipt after restart
- **THEN** recovery SHALL mark the child `LOST` or `INDETERMINATE` according to heartbeat/cancel evidence
- **AND** it SHALL NOT report success or repeat an unclassified side effect

### Requirement: Cancellation is explicitly classified

Supervisor cancellation SHALL return confirmed termination, unconfirmed termination, or unreachable/lost outcome. Unconfirmed or lost cancellation SHALL remain observable and SHALL block ordinary success/publication until Harness chooses a bounded retry, quarantine, or manual repair outcome.

#### Scenario: Cancellation is confirmed

- **WHEN** the provider returns a verified termination receipt for the child process
- **THEN** supervisor SHALL commit a cancelled terminal event
- **AND** the child SHALL not be scheduled again for the same attempt

#### Scenario: Cancellation cannot be confirmed

- **WHEN** the provider times out or loses contact before termination is verified
- **THEN** supervisor SHALL commit an indeterminate cancellation event
- **AND** recovery SHALL require evidence or controlled repair before publication
