# agent-loop-target-closure Specification

## Purpose
TBD - created by archiving change agent-loop-target-closure. Update Purpose after archive.
## Requirements
### Requirement: AgentLoop current implementation mapping
The AgentLoop target architecture SHALL document the current repository
implementation and classify capabilities as implemented, partial, or deferred.

#### Scenario: Document shows current code status
- **WHEN** developers read `docs/02-AGENT_LOOP_TARGET_ARCHITECTURE.md`
- **THEN** they can identify which AgentLoop capabilities are already implemented
  and which are not part of the current slice.

### Requirement: AgentLoop remains a single-agent runtime

AgentLoop SHALL execute one agent loop through LLM requests, tool observations, action parsing, output judging, retry, and result production without taking over Graph routing or final report quality governance. Harness Graph SHALL own outer node activation, budgets, deterministic gate verdicts, memory writes, tool authorization, approval state, and publication.

#### Scenario: AgentLoop is invoked from a Graph activity

- **WHEN** a Graph executable node binds an AgentLoop activity
- **THEN** the activity calls `AgentRunner`, which calls `AgentLoop`, while Graph routing stays owned by `HarnessControlPlane`

#### Scenario: AgentLoop produces an approval waiting candidate

- **WHEN** AgentLoop returns exactly one canonical approval request with deterministic waiting diagnostics
- **THEN** the activity succeeds with checksum-bound candidate output and evidence rather than changing the outer run state
- **AND** a deterministic Harness gate verifies the exact run, Graph id/version/checksum, node instance, attempt and tenant/identity scopes while preserving checksum-bound checkpoint/task-context lineage
- **AND** only an explicit Graph `Choice` may select `Wait(kind=approval)`, after which the Graph evaluator and reducer own durable registration and automatic resume
- **AND** AgentLoop, its worker and its binding do not register the Wait, decide the route, resume the Graph or publish a manifest

### Requirement: AgentRunner assembles dependencies only
AgentRunner SHALL assemble AgentSpec, LLMClient, ToolRegistry, ToolExecutor,
conversation store, prompt builder, parser, and output judge without embedding
daily intelligence business logic.

#### Scenario: AgentRunner executes with injected dependencies
- **WHEN** a test provides a fake LLM client and fake tool registry
- **THEN** AgentRunner runs the loop without direct provider SDK calls or direct
  business workflow access.

### Requirement: AgentLoop reports bounded diagnostics
AgentLoop SHALL include serializable diagnostics for retry exhaustion, parser
errors, judge retry exhaustion, tool budget blocks, and repeated tool-call
patterns.

#### Scenario: AgentLoop stops after retry exhaustion
- **WHEN** an agent repeatedly returns invalid output until retry limits are hit
- **THEN** the AgentLoopResult includes a failed status and diagnostics explaining
  the stop reason.

### Requirement: AgentLoop tests cover target closure behavior

AgentLoop closure SHALL include focused tests for parser recovery, output judge rules, tool calls, control output, conversation persistence, diagnostics, and Graph activity smoke integration.

#### Scenario: Focused AgentLoop tests run offline

- **WHEN** the AgentLoop focused tests run
- **THEN** they use fake LLM/tool dependencies and do not require network, provider credentials or a legacy Workflow runner

#### Scenario: AgentLoop diagnostics cannot authorize tools or budget

- **WHEN** an AgentLoop Graph worker reports requested tools, judge retries, structured-output diagnostics or budget observations
- **THEN** those values remain bounded candidate diagnostics
- **AND** only deterministic Harness gates and durable budget facts may authorize tools, accept outer output or halt/retry/replan the Graph
