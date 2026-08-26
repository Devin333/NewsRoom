## ADDED Requirements

### Requirement: Qualification covers process and provider failure

Production qualification SHALL execute or explicitly block scenarios for process restart, execution timeout, child loss, heartbeat timeout, confirmed cancellation, unconfirmed cancellation, duplicate event delivery, provider unavailability, and durable store failure.

#### Scenario: Parent process restarts during execution

- **WHEN** the parent process stops after an execution or child lease is committed but before the next control transition
- **THEN** recovery SHALL use durable receipts/events to select resume, retry, quarantine, or manual repair
- **AND** it SHALL not invoke an LLM or repeat a side effect merely because the in-memory state is absent

#### Scenario: Provider is unavailable

- **WHEN** Docker or another required provider is unavailable in the target deployment
- **THEN** qualification SHALL mark the capability blocked with environment evidence
- **AND** the system SHALL not claim production sandbox readiness or execute unisolated

### Requirement: Side effects are not repeated after uncertain results

Harness SHALL bind every externally visible side effect to an idempotency key and durable receipt. Before dispatch, the authorized attempt SHALL persist an immutable intent with `PREPARED` state. The provider and reconciliation port SHALL support the same key; receipt commit SHALL enqueue a terminal-event outbox. Retry or recovery SHALL read an identical existing receipt, reconcile `DISPATCHED` without a receipt, fail on a conflicting body, and never execute the side effect a second time for the same authorized attempt.

#### Scenario: Retry sees an identical receipt

- **WHEN** a retry encounters a durable side-effect receipt with the same authority and payload checksum
- **THEN** it SHALL return the original result
- **AND** the external handler invocation count SHALL remain one

#### Scenario: Retry sees an uncertain external result

- **WHEN** the process crashes after dispatch and before receiving the external result
- **THEN** Harness SHALL classify the result as indeterminate and query the canonical receipt/reconciliation path
- **AND** it SHALL not blindly dispatch the side effect again

#### Scenario: Crash occurs after dispatch before receipt

- **WHEN** an external call may have succeeded but the process crashes before `RECEIPT_COMMITTED`
- **THEN** recovery SHALL query the provider/reconciliation port using the immutable idempotency key
- **AND** it SHALL either record the authoritative receipt, classify `INDETERMINATE`, or quarantine for manual repair; it SHALL not issue an unverified second dispatch

#### Scenario: Crash occurs after receipt before event publication

- **WHEN** the authoritative receipt is durable but its terminal event has not been published
- **THEN** recovery SHALL publish the pending outbox record
- **AND** it SHALL not call the external handler again

### Requirement: Execution state transitions are crash-recoverable

Execution and side-effect intent state SHALL follow a versioned state machine `PREPARED -> DISPATCHED -> RECEIPT_COMMITTED -> EVENT_PUBLISHED`. Each transition SHALL be durable and idempotent, and each crash point SHALL map to one documented recovery branch.

#### Scenario: Prepared intent has no dispatch evidence

- **WHEN** recovery finds `PREPARED` with no provider dispatch or receipt evidence
- **THEN** Harness MAY dispatch exactly once using the same intent key
- **AND** it SHALL preserve the original authority and attempt identity

#### Scenario: Conflicting transition is observed

- **WHEN** recovery observes a transition with a stale version, different authority checksum, or conflicting receipt
- **THEN** it SHALL quarantine the attempt with a typed integrity conflict
- **AND** it SHALL not advance the state or execute a side effect

### Requirement: Evidence is reproducible and honest

Qualification evidence SHALL record commit, test command, provider/deployment capability, pass/skip/block status, event/receipt references, and unresolved external approval. Fake/in-memory tests MAY establish contract behavior but SHALL NOT be used as evidence of real isolation, cross-process durability, or production release qualification.

#### Scenario: Focused contract tests pass without Docker

- **WHEN** contract tests pass on a host whose Docker daemon is unavailable
- **THEN** evidence SHALL record the contract pass and Docker capability as blocked or skipped
- **AND** the release gate SHALL remain closed for Docker-backed production execution

#### Scenario: External release signature is missing

- **WHEN** durable event or Graph production release requires an independent deployment/rollback signature that is absent
- **THEN** the change SHALL remain implementation-complete but qualification-blocked
- **AND** tasks SHALL not be marked complete by substituting local test keys or fake deployment output

### Requirement: Qualification evidence has a durable artifact

The change SHALL maintain `openspec/changes/harness-runtime-production-composition/evidence.md` containing baseline commit/date, environment, manifest/provider fingerprints, durable-store capability, test commands and outcomes, real receipt/event references, skip/block reasons, and external release/rollback signatures. The file SHALL distinguish contract pass, integration pass, skip, blocked, and qualification-complete states.

#### Scenario: Evidence is updated after a test run

- **WHEN** a focused, integration, restart, or deployment qualification run completes
- **THEN** the evidence file SHALL record the exact command, commit, environment capability, result class, and relevant receipt/event reference
- **AND** a contract-only pass SHALL not be labeled as real isolation or cross-process production qualification
