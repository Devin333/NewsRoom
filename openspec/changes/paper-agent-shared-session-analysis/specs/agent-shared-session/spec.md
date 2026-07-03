## ADDED Requirements

### Requirement: Shared session runtime is framework-owned and generic
The system SHALL provide framework-level shared session refs, items, events, snapshots, stores, workspace, sanitization, access policy, compaction, lifecycle, and context assembly without importing business or interface modules.

#### Scenario: Framework import boundary is preserved
- **WHEN** import-boundary tests inspect `framework/agent/session`
- **THEN** no business, interface, paper, PublicPaper, provider, Redis, Qdrant, or concrete business term is present

### Requirement: Durable SQLite session store is available
The system SHALL provide a `SQLiteAgentSessionStore` that persists sessions, items, events, snapshots, and close state transactionally.

#### Scenario: SQLite store reopens persisted data
- **WHEN** a session item is written and the store is reopened from the same database path
- **THEN** the latest item for that session and role is still available

#### Scenario: SQLite store isolates sessions
- **WHEN** items are written under different session ids
- **THEN** queries and latest lookups only return items for the requested session id

### Requirement: MemoryRuntime bridge is available
The system SHALL provide session memory serializers, adapter, and `MemoryRuntimeAgentSessionStore` for writing session items and snapshots to MemoryRuntime.

#### Scenario: Session item is bridged to memory
- **WHEN** an item is appended through `MemoryRuntimeAgentSessionStore`
- **THEN** the adapter writes a sanitized `MemoryRecord` in an `agent_session:<session_id>` namespace

### Requirement: In-memory store is test-only compatible storage
The system SHALL keep `InMemoryAgentSessionStore` for tests and local compatibility but production paper ingest SHALL NOT default to it.

#### Scenario: Unit tests can use in-memory store
- **WHEN** tests create an `AgentSharedWorkspace` with `InMemoryAgentSessionStore`
- **THEN** items, events, snapshots, latest lookup, and clearing behave like the store protocol

### Requirement: Shared workspace sanitizes and validates writes
The shared workspace MUST reject empty identifiers and non-mapping content, MUST sanitize sensitive content and refs before persistence, and MUST record redacted field metadata.

#### Scenario: Sensitive fields are removed before storage
- **WHEN** content, refs, or metadata include `full_text`, `raw_payload`, `token`, `api_key`, authorization, cookies, or nested sensitive fields
- **THEN** stored session data does not expose those values and redacted field names are auditable

### Requirement: Access policy controls visibility
The system SHALL support public, shared, private, and final visibility plus role read/write policy.

#### Scenario: Private item remains private
- **WHEN** an item has private visibility
- **THEN** only the writing agent or orchestrator can read it through workspace policy

### Requirement: Session context can be assembled for prompts
The context assembler SHALL produce readable XML-like session context from sanitized items, skip private items, prioritize final items, and respect maximum character budgets.

#### Scenario: AgentLoop injects shared context only by policy
- **WHEN** an agent has enabled `session_context_policy` and inputs include `session_id`
- **THEN** AgentLoop injects assembled `shared_session_context` into LLM prompt inputs

### Requirement: Session compaction and lifecycle are auditable
The runtime SHALL compact long-running sessions into snapshots and record session lifecycle events.

#### Scenario: Snapshot keeps summaries and final item ids
- **WHEN** compaction runs over active/final items and events
- **THEN** the snapshot records role summaries, source event ids, and final item ids without copying raw item content

#### Scenario: Lifecycle close records terminal event
- **WHEN** a session completes or fails
- **THEN** `session.completed` or `session.failed` is appended to the event log

### Requirement: Sub-agent metadata can propagate session refs
Sub-agent execution SHALL pass `metadata.session_id`, `metadata.run_id`, and `metadata.workflow_id` into child inputs when no corresponding input value is already provided.

#### Scenario: Existing input session id remains authoritative
- **WHEN** a `SubAgentTask` contains both `inputs.session_id` and `metadata.session_id`
- **THEN** child inputs keep the value from `inputs.session_id`
