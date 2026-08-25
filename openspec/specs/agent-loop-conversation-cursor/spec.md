# agent-loop-conversation-cursor Specification

## Purpose
TBD - created by archiving change agent-loop-conversation-cursor. Update Purpose after archive.
## Requirements
### Requirement: Conversation store persists cursors

The conversation store SHALL persist and read a latest cursor record for each conversation. The cursor identity MAY reference a Graph run and Graph checkpoint, but MUST NOT require a Workflow runtime identity.

#### Scenario: Cursor round trip

- **WHEN** a cursor is written for a conversation
- **THEN** reading the cursor returns the same message offset, message id, run id, node-instance id, Graph checkpoint ref, and metadata

#### Scenario: Missing cursor

- **WHEN** no cursor has been written for a conversation
- **THEN** reading the cursor returns no cursor rather than failing

### Requirement: Conversation cursor storage is safe
The conversation store MUST validate cursor ids and redact cursor metadata
before persistence.

#### Scenario: Unsafe cursor input
- **WHEN** a cursor uses a path-traversal conversation id
- **THEN** cursor read/write rejects the input

#### Scenario: Cursor metadata contains sensitive value
- **WHEN** cursor metadata contains a secret-like value
- **THEN** the persisted cursor metadata stores a redacted value

### Requirement: AgentRunner maintains conversation cursor
AgentRunner SHALL write the latest conversation cursor after a persisted
conversation run completes.

#### Scenario: Cursor written after persisted run
- **WHEN** AgentRunner completes a run with a conversation store and conversation id
- **THEN** the conversation store contains a cursor with the current message offset,
  latest message id, agent id, status, iteration count, and stop reason metadata

#### Scenario: Cursor reflects compacted conversation
- **WHEN** AgentRunner compacts the conversation during persistence
- **THEN** the written cursor reflects the compacted readable message list rather
  than the pre-compaction append count

### Requirement: AgentRunner can provide cursor resume context

AgentRunner SHALL load an existing cursor as deterministic resume context only when the caller explicitly requests cursor resume, and SHALL include the latest AgentLoop iteration checkpoint when one exists. Any outer resume decision remains owned by Harness Graph.

#### Scenario: Resume context is injected

- **WHEN** AgentRunner is called with cursor resume enabled and a cursor exists
- **THEN** the loop inputs include the serialized conversation cursor and latest conversation summary

#### Scenario: Iteration checkpoint resume context is injected

- **WHEN** AgentRunner is called with cursor resume enabled and an AgentLoop iteration checkpoint exists
- **THEN** the loop inputs include the serialized AgentLoop iteration checkpoint

#### Scenario: Resume context is absent by default

- **WHEN** AgentRunner is called without cursor resume enabled
- **THEN** the loop inputs do not include conversation cursor resume metadata or AgentLoop iteration checkpoint metadata
