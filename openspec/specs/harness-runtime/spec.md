## Purpose
Define the Harness control plane, bounded phase model, deterministic gates, replaceable ports, isolated subagents, context assembly, RAG bounds, and replay obligations for Harness-managed runs.
## Requirements
### Requirement: Harness Control Plane Authority
The Harness runtime SHALL be the only workflow decision maker for Harness-managed runs. LLM workers, AgentLoop workers, tool workers, subagents, skill workers, RAG workers, interface services, and business steps MUST NOT decide workflow routing, quality verdicts, memory writes, tool authorization, approval state, or artifact publication. Worker-provided scores, verdict-shaped values, and route suggestions are candidate observations only and MUST NOT be consumed as Harness decision inputs.

#### Scenario: Worker output cannot route a run
- **WHEN** a worker result contains a suggested next route or quality verdict
- **THEN** Harness MUST treat that value as candidate data only
- **AND** Harness MUST choose the next route from workflow spec, current state, policy, budgets, and deterministic gate results

#### Scenario: Worker self-evaluation is observational
- **WHEN** an LLM or subagent returns a self-evaluation observation
- **THEN** Harness MUST NOT convert that observation into `HarnessQualityVerdict`
- **AND** the observation MUST NOT select retry, replan, repair, halt, completion, memory write, approval, or publication

### Requirement: Phase State Machine
Harness-managed steps SHALL advance through bounded `PLAN -> EXECUTE -> VERIFY` phases. `PLAN` SHALL select the execution plan, `EXECUTE` SHALL call controlled workers, and `VERIFY` SHALL run deterministic gates before any state transition is accepted.

#### Scenario: Step advances through all phases
- **WHEN** Harness runs a step with valid inputs and an accepted worker result
- **THEN** the run transcript MUST record `PLAN`, `EXECUTE`, and `VERIFY` phase events in order
- **AND** the step MUST NOT publish final outputs before VERIFY passes

### Requirement: Controlled Failure Outcomes
When VERIFY fails or budgets are exhausted, Harness SHALL choose only explicit controlled outcomes: `replan`, `retry`, `route_to_repair`, `wait_for_approval`, `halted`, or `failed`.

#### Scenario: Budget exhaustion halts the run
- **WHEN** a Harness run exceeds `max_turns`, `max_replans`, `max_retries_per_step`, or `max_worker_calls`
- **THEN** Harness MUST transition the run to `halted`
- **AND** Harness MUST record the exhausted budget in the run transcript

### Requirement: Harness Port Boundaries
Harness SHALL consume external capabilities through replaceable ports for LLM, tools, memory, skills, artifacts, events, workers, governance, context, subagents, and RAG. Production implementations MAY reuse existing framework modules, but routing authority MUST remain in Harness.

#### Scenario: Port implementation is replaceable
- **WHEN** a test run supplies fake LLM, memory, tool, artifact, and event ports
- **THEN** Harness MUST execute the same phase and gate rules without importing concrete infrastructure adapters

### Requirement: Deterministic VERIFY Gates
Harness VERIFY gates SHALL be deterministic functions for schema validation, budget checks, score ranges, evidence coverage, source references, tool allowlists, memory namespaces, duplicate checks, and publication readiness. For each step, Harness MUST execute the framework mandatory gates plus only the exact declared gate and its deterministic dependencies. LLM self-evaluation MUST NOT replace a VERIFY gate.

#### Scenario: LLM self-evaluation is insufficient
- **WHEN** an LLM worker returns text claiming the result is valid
- **THEN** Harness MUST still run the configured deterministic gates
- **AND** Harness MUST reject the result if any required gate fails

#### Scenario: Only current step gate executes
- **WHEN** a workflow contains steps with different declared quality gates
- **THEN** VERIFY MUST execute the current step's bound gate and framework mandatory gates in stable order
- **AND** Harness MUST NOT execute unrelated domain gates registered for other steps

#### Scenario: Gate execution raises an exception
- **WHEN** a required deterministic gate raises or returns an invalid result
- **THEN** Harness MUST record a stable failed gate outcome
- **AND** the scheduler MUST choose an allowed controlled failure outcome within the existing budgets

### Requirement: Subagent Isolation
Harness SHALL isolate subagents with independent context, private history, explicit handoff payloads, tool allowlists, memory namespaces, and transcripts. Subagents MUST NOT read sibling transcripts, raw parent context, hidden prompts, or unauthorized memory namespaces.

#### Scenario: Cross-subagent data uses approved handoff
- **WHEN** one subagent output is needed by another subagent
- **THEN** Harness MUST serialize it through an approved handoff schema
- **AND** a gate MUST validate the handoff before the receiving subagent can consume it

### Requirement: Context Engineering Assembly
Harness SHALL assemble worker context from explicit stable prefix and dynamic tail sections. Global policy, workflow route table, schemas, gate definitions, tool allowlists, memory namespace policy, source refs, and budget values MUST NOT be compressed away or placed only in dynamic summaries.

#### Scenario: Critical control material survives compression
- **WHEN** context budget pressure requires compression
- **THEN** Harness MUST preserve policy, schema, gate, allowlist, namespace, source ref, and budget sections verbatim or through lossless references
- **AND** dynamic worker outputs MAY be summarized only outside the stable prefix

### Requirement: Bounded Agentic RAG
Harness SHALL control multi-round retrieval, source reads, verification, gap filling, and `RAGContextPack` assembly. RAG loops MUST declare `max_rounds`, `max_queries`, `max_source_reads`, `max_memory_hits`, and context budget.

#### Scenario: RAG loop stops at declared bounds
- **WHEN** a RAG worker requests additional retrieval after the configured limit is reached
- **THEN** Harness MUST stop retrieval
- **AND** Harness MUST record a bounded RAG outcome for VERIFY to evaluate

### Requirement: Trace Checkpoint Replay
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, and artifact publication decisions to a durable transcript or event log that can support checkpointing and replay. Gate evidence MUST include the exact gate id and version, deterministic input reference, result reference, pass/fail outcome, stable reason code, aggregate verdict, and resulting scheduler decision before the next state or publication is accepted.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, and artifact decision events without calling an LLM

#### Scenario: Recovery resumes after committed VERIFY
- **WHEN** VERIFY evidence and its transition were durably committed before a process crash
- **THEN** recovery MUST use the recorded gate evidence and pinned gate version as scheduler input
- **AND** recovery MUST NOT replace the recorded verdict with current defaults or worker self-evaluation

#### Scenario: Recorded gate evidence is incomplete
- **WHEN** recovery cannot resolve the pinned gate version or verify the recorded gate evidence checksum
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST NOT guess, reclassify the history as passed, or invoke an LLM

### Requirement: Versioned Gate Binding
Harness SHALL resolve every declared `HarnessStepSpec.quality_gate` to one exact deterministic gate id and version before recording run creation or invoking a worker. The registry MUST reject unknown gates, unversioned declarations, duplicate or ambiguous registrations, incompatible versions, missing dependencies, and dependency cycles.

#### Scenario: Unknown declared gate fails before execution
- **WHEN** a workflow step declares `DefinitelyMissingGate@1`
- **THEN** Harness MUST reject the run before recording a worker call
- **AND** the run MUST NOT be reported as succeeded

#### Scenario: Gate dependency cannot be resolved
- **WHEN** a registered gate references a missing or cyclic deterministic dependency
- **THEN** Harness MUST fail closed during workflow preflight
- **AND** Harness MUST identify the invalid gate reference without executing any gate or worker

#### Scenario: Exact gate version is pinned
- **WHEN** a workflow step declares `ClaimEvidenceGate@2`
- **THEN** Harness MUST bind exactly version `2` for that run
- **AND** a later default registration MUST NOT replace the pinned implementation during recovery or replay

### Requirement: Deterministic Gate Aggregation
Harness SHALL construct `HarnessQualityVerdict` only by deterministically aggregating the required gate results for the current step. A missing result, gate exception, invalid result, identity mismatch, or failed required gate MUST produce a failed verification outcome and MUST NOT default to pass.

#### Scenario: High worker score cannot override a failed gate
- **WHEN** a worker reports a high self-evaluation score and a required deterministic gate fails
- **THEN** the aggregate Harness quality verdict MUST fail
- **AND** the worker score MUST NOT alter routing or the controlled failure outcome

#### Scenario: Step has no declared quality gate
- **WHEN** a framework utility step has no declared quality gate and no `ON_VERDICT` route
- **THEN** Harness MAY execute its framework mandatory gates
- **AND** Harness MUST NOT manufacture a routable quality verdict for that step

#### Scenario: Verdict route requires a declared gate
- **WHEN** an `ON_VERDICT` routing rule originates from a step without a declared deterministic quality gate
- **THEN** workflow preflight MUST reject the workflow before worker execution
