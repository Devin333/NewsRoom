## REMOVED Requirements

### Requirement: Workflow captures AgentLoop LLM call artifacts

**Reason**：`Workflow Runtime` 和 `WorkflowExecutor` 退役；LLM call artifact 是 AgentLoop activity 的候选证据，由 artifact owner 按 Harness 生命周期持久化。

**Migration**：Graph activity receipt 提供 node-instance/run context，artifact publisher 写入 redacted LLM call records；Graph manifest 只接受 Harness 验证后的 artifact refs。

## ADDED Requirements

### Requirement: Graph activity captures AgentLoop LLM call artifacts

Graph AgentLoop activities SHALL persist redacted LLM call request/response artifacts through the artifact-owned port and include checksum-bound refs in the node outcome and Graph run manifest. `AgentLoop` SHALL not publish artifacts or decide manifest acceptance.

#### Scenario: Graph AgentLoop activity completes with LLM calls

- **WHEN** a Graph AgentLoop activity produces one or more LLM calls
- **THEN** the artifact owner writes redacted LLM call JSON with checksum, size, type, Graph run id and node-instance metadata
- **AND** Harness records the refs only after deterministic artifact and output gates pass

#### Scenario: AgentLoop attempts direct publication

- **WHEN** AgentLoop returns a candidate that includes an unverified artifact path or publication instruction
- **THEN** Harness treats it as candidate data and does not add it to the Graph manifest
