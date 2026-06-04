## Purpose
Define the Harness control plane, bounded phase model, deterministic gates, replaceable ports, isolated subagents, context assembly, RAG bounds, and replay obligations for Harness-managed runs.

## Requirements

### Requirement: Harness Control Plane Authority
The Harness runtime SHALL be the only workflow decision maker for Harness-managed runs. LLM workers, AgentLoop workers, tool workers, subagents, skill workers, RAG workers, interface services, and business steps MUST NOT decide workflow routing, quality verdicts, memory writes, tool authorization, approval state, or artifact publication.

#### Scenario: Worker output cannot route a run
- **WHEN** a worker result contains a suggested next route or quality verdict
- **THEN** Harness MUST treat that value as candidate data only
- **AND** Harness MUST choose the next route from workflow spec, current state, policy, budgets, and deterministic gate results

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
Harness VERIFY gates SHALL be deterministic functions for schema validation, budget checks, score ranges, evidence coverage, source references, tool allowlists, memory namespaces, duplicate checks, and publication readiness. LLM self-evaluation MUST NOT replace a VERIFY gate.

#### Scenario: LLM self-evaluation is insufficient
- **WHEN** an LLM worker returns text claiming the result is valid
- **THEN** Harness MUST still run the configured deterministic gates
- **AND** Harness MUST reject the result if any required gate fails

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
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, and artifact publication decisions to a durable transcript or event log that can support checkpointing and replay.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, and artifact decision events without calling an LLM
