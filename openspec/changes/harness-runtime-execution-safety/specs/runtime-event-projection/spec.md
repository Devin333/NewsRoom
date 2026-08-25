## ADDED Requirements

### Requirement: Runtime facts use one canonical event envelope
Turn, tool, approval, context compaction, worker, and child-agent lifecycle facts SHALL be appended through the canonical durable event port with stable event identity, schema revision, sequence, Graph/activity/attempt identity, timestamps, status, reason code, and refs/checksums.

#### Scenario: Tool terminal fact is projected
- **WHEN** a tool attempt reaches a terminal state
- **THEN** the event stream contains a redacted terminal fact bound to the exact tool attempt and execution receipt

#### Scenario: Identity conflict is rejected
- **WHEN** an event carries conflicting Graph or attempt identity fields
- **THEN** canonical append rejects the event and does not expose it as an operator status

### Requirement: Runtime events are redacted and reference bounded
Ordinary runtime events SHALL exclude secrets, raw prompts, complete tool payloads, file contents, and unauthorized evidence bodies, and SHALL use bounded refs/checksums for oversized or protected content.

#### Scenario: Secret is removed before append
- **WHEN** a tool or worker diagnostic contains a configured secret
- **THEN** durable append stores only the redacted diagnostic and approved reference metadata

#### Scenario: Protected payload lacks an authorized store
- **WHEN** an event would require persisting protected content but no authorized secure payload store is available
- **THEN** append fails closed or records a typed protected-payload rejection without writing the content

### Requirement: Projection is idempotent and replay-safe
The runtime projection SHALL be rebuildable from canonical events, deduplicate by event identity, support bounded cursor/resume reads, and SHALL never make routing, quality, authorization, memory, or publication decisions.

#### Scenario: Duplicate delivery does not duplicate status
- **WHEN** the same durable event is delivered to the projection more than once
- **THEN** the projection contains one logical status transition and one cursor position

#### Scenario: Projection rebuild does not rerun effects
- **WHEN** an operator rebuilds runtime status from canonical history
- **THEN** the rebuild reads recorded results only and does not invoke tools, child agents, approvals, or external side effects

### Requirement: Operator can inspect bounded runtime status
The application service and read API SHALL expose safe status and timeline queries by run, node, activity, attempt, child, and cursor, while write operations continue through existing Harness wait, approval, cancellation, and resume contracts.

#### Scenario: Operator reconnects with a cursor
- **WHEN** an operator requests events after a previously committed cursor
- **THEN** the service returns ordered redacted events after that cursor or a typed cursor conflict

#### Scenario: UI cannot route a Graph
- **WHEN** a client submits a projection query or status update
- **THEN** the query is read-only and any mutation is rejected unless it uses the existing application-service approval/cancel contract
