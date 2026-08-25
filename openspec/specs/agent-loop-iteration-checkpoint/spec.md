# agent-loop-iteration-checkpoint Specification

## Purpose
TBD - created by archiving change agent-loop-iteration-checkpoint. Update Purpose after archive.
## Requirements
### Requirement: Conversation store persists AgentLoop iteration checkpoint

The conversation store SHALL persist and read the latest AgentLoop iteration checkpoint for a conversation. The checkpoint MAY reference one Graph run, node instance and Graph checkpoint, but SHALL NOT require Workflow runtime identity.

#### Scenario: Iteration checkpoint round trip

- **WHEN** an iteration checkpoint is written for a conversation
- **THEN** reading the checkpoint returns the same conversation id, agent id, run id, node-instance id, Graph checkpoint ref, status, iteration count, stop reason, trace summary, diagnostics summary, LLM artifact ids, and metadata

#### Scenario: Missing iteration checkpoint

- **WHEN** no iteration checkpoint has been written for a conversation
- **THEN** reading the checkpoint returns no checkpoint rather than failing

### Requirement: Iteration checkpoint storage is safe
The conversation store MUST validate iteration checkpoint ids and redact checkpoint metadata before persistence.

#### Scenario: Unsafe checkpoint input
- **WHEN** an iteration checkpoint uses a path-traversal conversation id
- **THEN** checkpoint read/write rejects the input

#### Scenario: Checkpoint metadata contains sensitive value
- **WHEN** checkpoint metadata contains a secret-like value
- **THEN** the persisted checkpoint metadata stores a redacted value

### Requirement: AgentRunner writes iteration checkpoint
AgentRunner SHALL write a latest AgentLoop iteration checkpoint after a persisted conversation run completes.

#### Scenario: Accepted run writes iteration checkpoint
- **WHEN** AgentRunner completes an accepted run with a conversation store and conversation id
- **THEN** the conversation store contains an iteration checkpoint with accepted status, iteration count, stop reason, trace summary, diagnostics summary, and LLM call artifact ids

#### Scenario: Paused run writes iteration checkpoint
- **WHEN** AgentRunner stops waiting for approval with a conversation store and conversation id
- **THEN** the iteration checkpoint includes waiting status, approval metadata, and the latest tool observation metadata needed to explain the pause boundary
