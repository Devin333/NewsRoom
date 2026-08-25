## MODIFIED Requirements

### Requirement: Conversation store persists AgentLoop iteration checkpoint

The conversation store SHALL persist and read the latest AgentLoop iteration checkpoint for a conversation. The checkpoint MAY reference one Graph run, node instance and Graph checkpoint, but SHALL NOT require Workflow runtime identity.

#### Scenario: Iteration checkpoint round trip

- **WHEN** an iteration checkpoint is written for a conversation
- **THEN** reading the checkpoint returns the same conversation id, agent id, run id, node-instance id, Graph checkpoint ref, status, iteration count, stop reason, trace summary, diagnostics summary, LLM artifact ids, and metadata

#### Scenario: Missing iteration checkpoint

- **WHEN** no iteration checkpoint has been written for a conversation
- **THEN** reading the checkpoint returns no checkpoint rather than failing
