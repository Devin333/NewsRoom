## MODIFIED Requirements

### Requirement: Conversation store persists cursors

The conversation store SHALL persist and read a latest cursor record for each conversation. The cursor identity MAY reference a Graph run and Graph checkpoint, but MUST NOT require a Workflow runtime identity.

#### Scenario: Cursor round trip

- **WHEN** a cursor is written for a conversation
- **THEN** reading the cursor returns the same message offset, message id, run id, node-instance id, Graph checkpoint ref, and metadata

#### Scenario: Missing cursor

- **WHEN** no cursor has been written for a conversation
- **THEN** reading the cursor returns no cursor rather than failing

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
