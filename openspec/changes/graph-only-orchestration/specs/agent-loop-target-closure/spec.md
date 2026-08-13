## MODIFIED Requirements

### Requirement: AgentLoop remains a single-agent runtime

AgentLoop SHALL execute one agent loop through LLM requests, tool observations, action parsing, output judging, retry, and result production without taking over Graph routing or final report quality governance. Harness Graph SHALL own outer node activation, budgets, deterministic gate verdicts, memory writes, tool authorization, approval state, and publication.

#### Scenario: AgentLoop is invoked from a Graph activity

- **WHEN** a Graph executable node binds an AgentLoop activity
- **THEN** the activity calls `AgentRunner`, which calls `AgentLoop`, while Graph routing stays owned by `HarnessControlPlane`

### Requirement: AgentLoop tests cover target closure behavior

AgentLoop closure SHALL include focused tests for parser recovery, output judge rules, tool calls, control output, conversation persistence, diagnostics, and Graph activity smoke integration.

#### Scenario: Focused AgentLoop tests run offline

- **WHEN** the AgentLoop focused tests run
- **THEN** they use fake LLM/tool dependencies and do not require network, provider credentials or a legacy Workflow runner
