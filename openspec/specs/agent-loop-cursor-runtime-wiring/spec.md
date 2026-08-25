# agent-loop-cursor-runtime-wiring Specification

## Purpose
TBD - created by archiving change agent-loop-cursor-runtime-wiring. Update Purpose after archive.
## Requirements
### Requirement: AgentRunner writes conversation cursor
AgentRunner SHALL write a latest conversation cursor after a run persists
conversation messages when a conversation store and conversation id are
configured.

#### Scenario: Direct AgentRunner run writes cursor
- **WHEN** AgentRunner completes a run with a conversation store and
  conversation id
- **THEN** the store contains a cursor pointing at the latest active
  conversation message
- **AND** the cursor metadata includes agent status and iteration count

#### Scenario: Cursor follows compaction
- **WHEN** AgentRunner compacts the conversation after persistence
- **THEN** the cursor points at the latest retained active conversation message

### Requirement: Graph AgentLoop activities pass cursor context

Graph AgentLoop activity bindings SHALL pass Graph run, node-instance and checkpoint context to `AgentRunner` when executing a bound AgentLoop.

#### Scenario: Graph activity writes contextual cursor

- **WHEN** a Graph AgentLoop activity runs with a configured conversation id
- **THEN** the conversation cursor includes the Graph run id, node-instance id and Graph checkpoint ref
