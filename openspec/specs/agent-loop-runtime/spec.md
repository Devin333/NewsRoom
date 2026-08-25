# agent-loop-runtime Specification

## Purpose
TBD - created by archiving change agent-loop-tool-runtime-runner. Update Purpose after archive.
## Requirements
### Requirement: FakeLLM is deterministic and offline
The system SHALL provide a FakeLLM client that returns scripted responses without network access, provider keys, or real LLM calls.

#### Scenario: FakeLLM returns scripted response
- **WHEN** AgentLoop requests a model response from FakeLLM
- **THEN** FakeLLM returns the next scripted response and records simulated token usage

### Requirement: AgentLoop handles tool actions and observations
The system SHALL parse model responses into AgentAction records and execute tool call actions through ToolExecutor.

#### Scenario: Tool action is observed before final output
- **WHEN** FakeLLM returns a tool_call action followed by a final_output action
- **THEN** AgentLoop records agent start, LLM call, tool call, tool observation, and final output events

### Requirement: OutputJudge validates final output
The system SHALL validate final output for required output key, allowed tools, source boundaries, and obvious secrets before accepting it.

#### Scenario: Missing output key triggers retry
- **WHEN** final output does not include the AgentSpec output key
- **THEN** OutputJudge returns retry and AgentLoop asks FakeLLM for another response until retry budget is exhausted or output is accepted

#### Scenario: Secret-like output is blocked
- **WHEN** final output contains an obvious API key pattern
- **THEN** OutputJudge blocks the AgentLoop result

### Requirement: AgentRunner assembles single-agent runs
The system SHALL provide AgentRunner that assembles AgentSpec, FakeLLM,
ToolRegistry, ToolExecutor, parser, judge, AgentLoop, optional conversation
compaction, and conversation cursor updates for single-agent validation.

#### Scenario: AgentRunner returns accepted result
- **WHEN** AgentRunner runs a scripted agent with an allowed fake tool and valid final output
- **THEN** it returns an accepted AgentLoopResult with metrics for llm calls, tool calls, and token usage

#### Scenario: AgentRunner compacts persisted conversations
- **WHEN** AgentRunner writes conversation messages and the agent compaction threshold is exceeded
- **THEN** it triggers the conversation store to retain a compact summary marker and the newest messages

#### Scenario: AgentRunner records latest conversation cursor
- **WHEN** AgentRunner writes persisted conversation messages
- **THEN** it writes a latest conversation cursor that can link active message position to run, step, and checkpoint context

### Requirement: AgentLoop pauses on human escalation control tools
AgentLoop SHALL treat successful `control.request_human_review` and
`control.escalate` observations that include an approval id as explicit
waiting-for-approval pause points.

#### Scenario: Human review control pauses the loop
- **WHEN** an agent calls `control.request_human_review` and the tool creates an approval request
- **THEN** AgentLoop returns a waiting-for-approval result that includes the approval id in events and diagnostics

#### Scenario: Escalation control pauses the loop
- **WHEN** an agent calls `control.escalate` and the tool creates an approval request
- **THEN** AgentLoop returns a waiting-for-approval result that includes the approval id and escalation type in events and diagnostics

#### Scenario: Approval replay remains out of scope
- **WHEN** an approval decision is later recorded outside AgentLoop
- **THEN** AgentLoop does not attempt mid-iteration replay in this capability

### Requirement: Approval decisions provide Graph resume context
The system SHALL provide bounded read-only Graph Wait and approval context for decided approval records. Callers SHALL submit only the approval decision identity and SHALL NOT provide state patches, buffer updates, resume metadata, or routing intent.

#### Scenario: Approved decision produces typed approval cause
- **WHEN** an approval request has an approved decision
- **THEN** the approval service resolves the current Graph run and durable Wait scope, then submits checksum-bound approval evidence as a typed cause
- **AND** Harness durably commits the cause before automatically resuming Graph evaluation

#### Scenario: Pending approval cannot produce resume context
- **WHEN** an approval request has no recorded decision
- **THEN** the approval service rejects resume context creation for that approval

#### Scenario: Graph resume records approval evidence
- **WHEN** Harness resumes evaluation after accepting an approval cause
- **THEN** durable Graph history records the approval evidence reference, actor scope, and exact Wait scope without caller-supplied state patches
