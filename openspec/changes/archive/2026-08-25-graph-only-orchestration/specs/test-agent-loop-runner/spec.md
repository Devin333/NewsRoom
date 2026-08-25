## MODIFIED Requirements

### Requirement: Test agent loop runner is available

The system SHALL provide a `test-agent-loop` Graph that validates FakeLLM, ToolRuntime, AgentLoop, OutputJudge, tool observation, judge retry, activity binding, deterministic gate, and metrics without a legacy Workflow runner.

#### Scenario: Test AgentLoop Graph succeeds

- **WHEN** the `test-agent-loop` Graph runs
- **THEN** it succeeds without real network or real LLM calls and writes deterministic AgentLoop output
- **AND** Graph preflight, activity execution and VERIFY evidence are present

### Requirement: CLI smoke command uses application service

The system SHALL expose `news dev run-test-agent-loop` and execute it through the Graph run application service and activity-binding assembly rather than directly constructing low-level components in the CLI command.

#### Scenario: CLI smoke succeeds

- **WHEN** an operator runs `news dev run-test-agent-loop`
- **THEN** the command exits with status 0 and prints run status, run id, Graph ref, artifact path, llm calls, and tool calls

### Requirement: AgentLoop smoke artifacts include events and metrics

The system SHALL write Graph-run artifacts that include agent start, LLM call, tool call, tool observation, judge retry, final output, deterministic VERIFY evidence, llm call count, tool call count, and simulated token usage.

The smoke SHALL use the retained artifact owner for internal Graph artifacts. AgentLoop and its worker SHALL NOT write the terminal manifest or gain publication authority.

#### Scenario: Smoke Graph manifest exposes metrics

- **WHEN** the `test-agent-loop` Graph terminal manifest is written
- **THEN** manifest output includes nonzero fake llm_calls, tool_calls, token usage, and the verified node-instance ref
- **AND** every member is an artifact-owner-verified internal Graph artifact and publication remains absent
