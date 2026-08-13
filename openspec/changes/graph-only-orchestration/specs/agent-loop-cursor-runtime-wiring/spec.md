## REMOVED Requirements

### Requirement: Workflow AgentLoop steps pass cursor context

**Reason**：`AgentLoopStepRunner` 和 Workflow step context 属于被删除的 outer runtime。

**Migration**：Graph AgentLoop activity binding 传递 `graph_run_id`、`node_instance_id`、`graph_checkpoint_id` 和 conversation identity。

## ADDED Requirements

### Requirement: Graph AgentLoop activities pass cursor context

Graph AgentLoop activity bindings SHALL pass Graph run, node-instance and checkpoint context to `AgentRunner` when executing a bound AgentLoop.

#### Scenario: Graph activity writes contextual cursor

- **WHEN** a Graph AgentLoop activity runs with a configured conversation id
- **THEN** the conversation cursor includes the Graph run id, node-instance id and Graph checkpoint id
