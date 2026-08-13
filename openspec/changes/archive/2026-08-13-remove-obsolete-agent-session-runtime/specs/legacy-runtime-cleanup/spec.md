## ADDED Requirements

### Requirement: Retire Obsolete Agent Shared-Session Runtime
After Harness durable transcript replacement acceptance, cleanup SHALL remove `framework/agent/session`, `framework/memory/session`, their dedicated tests, `AgentSessionContextPolicy`, AgentLoop shared-session prompt injection, and special subagent metadata propagation. The runtime MUST NOT retain a compatibility re-export, fallback store, no-op implementation, hidden workspace input, or feature flag that recreates the retired state plane.

#### Scenario: Repository is inspected after retirement
- **WHEN** architecture checks inspect production and test source
- **THEN** the obsolete package directories, retired symbols, imports, exports, hooks, and dedicated tests MUST be absent
- **AND** production MUST expose no replacement compatibility layer or implicit shared-session fallback

#### Scenario: Stale AgentSpec policy is loaded
- **WHEN** `AgentSpec.from_dict()` receives the retired `session_context_policy` key
- **THEN** it MUST reject the payload with a stable validation error
- **AND** it MUST NOT silently ignore the policy or assemble shared session content

#### Scenario: Legacy subagent metadata contains session id
- **WHEN** a legacy `SubAgentTask` carries `session_id` only in metadata
- **THEN** `_child_inputs()` MUST NOT promote that value into child inputs
- **AND** normal run and workflow correlation metadata MUST remain available through their existing owners

### Requirement: Agent Execution Has No Shared-Session State Plane
`AgentLoop` and `AgentRunner` SHALL execute bounded agent turns without accepting a shared-session store, workspace, context assembler, or hidden workspace input. `AgentRunner` MUST NOT gain session persistence authority as part of this retirement.

#### Scenario: AgentLoop and AgentRunner signatures are inspected
- **WHEN** architecture checks inspect constructors and run methods
- **THEN** neither public surface SHALL accept session store/workspace/context-assembler parameters
- **AND** AgentLoop MUST NOT inspect `_agent_session_workspace` or inject `shared_session_context`

#### Scenario: Ordinary AgentSpec roundtrips
- **WHEN** an AgentSpec without retired fields is serialized and restored
- **THEN** the roundtrip MUST preserve its supported fields
- **AND** the serialized payload MUST NOT contain `session_context_policy`

### Requirement: Preserve Independently Owned Session Capabilities
Retirement SHALL preserve Harness RAG sessions, Research reading sessions, auth/project sessions, persisted conversations, conversation cursors and compaction, and generic run/workflow/step correlation. Cleanup MUST be scoped by package ownership and retired symbol, not by the text `session` or `session_id` alone.

#### Scenario: Retained session suites run
- **WHEN** RAG, Research, authentication/project, conversation cursor, and conversation compaction regressions execute after cleanup
- **THEN** their accepted behavior MUST remain available
- **AND** none of those modules may import the retired agent session packages

### Requirement: Preserve Superseded Shared-Session History Without Spec Sync
The completed `paper-agent-shared-session-analysis` change SHALL be archived as superseded history with spec synchronization skipped. Its `agent-shared-session`, paper orchestrator, and SQLite session requirements MUST NOT be merged into canonical specs.

#### Scenario: Historical change is archived
- **WHEN** maintainers archive `paper-agent-shared-session-analysis`
- **THEN** they MUST use `openspec archive paper-agent-shared-session-analysis --skip-specs`
- **AND** canonical spec content checksums before and after the archive MUST be identical
