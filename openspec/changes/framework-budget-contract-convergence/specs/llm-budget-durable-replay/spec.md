## ADDED Requirements

### Requirement: Versioned public budget snapshot and restore
Canonical snapshots SHALL include schema version, policy digest, scope graph and policies required for validation, committed and reserved usage, bounded open reservations, bounded terminal idempotency records, last event identity, and monotonic ledger revision. Restore SHALL validate all fields and invariants before exposing a ledger and MUST NOT require private-field mutation.

#### Scenario: Snapshot restore preserves authority state
- **WHEN** a valid snapshot containing committed usage and open reservations is restored
- **THEN** usage, remaining capacity, operation states, policy digest, last event identity, and ledger revision match the source

#### Scenario: Unknown snapshot fails closed
- **WHEN** a snapshot has an unknown version, field, policy digest, invalid scope graph, or inconsistent total
- **THEN** restore raises a typed history error
- **AND** no partially restored ledger is returned

### Requirement: Canonical durable budget events
Budget lifecycle facts SHALL use the existing canonical event schema catalog, event candidate, and durable store authority. Registered facts SHALL cover reservation created, denied, settled, released or expired, and indeterminate outcomes and SHALL include run id, scope reference, policy digest, operation/reservation identity when applicable, ledger revision, bounded amounts, outcome, and stable reason codes.

#### Scenario: Event schema validates a settlement
- **WHEN** a settlement fact is projected to the canonical event runtime
- **THEN** the catalog validates it under the current budget event schema
- **AND** the event contains enough bounded facts to replay the mutation

### Requirement: Budget evidence is bounded and redacted
Snapshot, event, decision, and diagnostics serialization SHALL output JSON-safe primitives from an allowlist and MUST NOT contain raw prompt, messages, tool payload, provider response, exception, traceback, credential, secret, or arbitrary caller metadata. Reason codes and collection sizes SHALL be bounded and deterministically ordered.

#### Scenario: Sensitive input is not serializable into budget evidence
- **WHEN** an adapter handles a request containing prompts, tool arguments, secrets, and a provider body
- **THEN** canonical budget snapshots and events contain only identity, policy, amount, outcome, and bounded reason projections

### Requirement: Offline replay is strict and side-effect free
Offline replay SHALL rebuild budget state only from validated canonical snapshots and ordered budget events. It MUST make zero LLM, provider, cache, tool, memory, or publication calls and SHALL fail closed on missing, conflicting, duplicate, unknown, or out-of-order authority-bearing facts.

#### Scenario: Replay reaches identical terminal state
- **WHEN** a valid snapshot and subsequent ordered budget events are replayed
- **THEN** the rebuilt usage, open reservations, terminal records, policy digest, revision, and final decision equal the live ledger
- **AND** external invocation counts remain zero

#### Scenario: Revision gap fails closed
- **WHEN** replay observes a missing or out-of-order ledger revision
- **THEN** it raises a typed history diagnostic
- **AND** it does not guess state or invoke a worker

### Requirement: Legacy flat snapshots are read-only migration inputs
The migration decoder SHALL accept the bounded known legacy flat cumulative-usage shape and map it to a canonical root snapshot with no fabricated open reservation. New runtime writes MUST use the canonical schema and MUST NOT write legacy fields or restore by assigning `_usage`.

#### Scenario: Legacy snapshot migrates once
- **WHEN** a supported legacy flat snapshot is loaded
- **THEN** it produces a validated canonical root state
- **AND** the next snapshot write uses only the canonical versioned schema
