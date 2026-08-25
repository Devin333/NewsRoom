## Purpose
Define the Harness control plane, bounded phase model, deterministic gates, replaceable ports, isolated subagents, context assembly, RAG bounds, and replay obligations for Harness-managed runs.
## Requirements
### Requirement: Harness Control Plane Authority

The Harness runtime SHALL be the only Graph and TaskPlan decision maker for Harness-managed runs. `HarnessScheduler` MAY internally compose TaskPlan validation and ready-task scheduling for an explicitly registered dynamic stage, but those components MUST NOT become a competing Graph authority. LLM workers, AgentLoop workers, tool workers, subagents, skill workers, RAG workers, interface services, business steps, and queue workers MUST NOT decide Graph routing, accepted plan versions, actual worker bindings, task readiness, quality verdicts, memory writes, tool authorization, approval state, or artifact publication. Worker-provided scores, verdict-shaped values, route suggestions, task decompositions, capability hints, and plan patches are candidate observations only and MUST NOT be consumed as accepted control decisions until Harness validates and durably accepts them.

#### Scenario: Worker output cannot route a Graph

- **WHEN** a worker result contains a suggested next node or quality verdict
- **THEN** Harness MUST treat that value as candidate data only
- **AND** Harness MUST choose the next node from the pinned Graph, current state, policy, budgets, and deterministic gate results

#### Scenario: Worker self-evaluation is observational

- **WHEN** an LLM or subagent returns a self-evaluation observation
- **THEN** Harness MUST NOT convert that observation into `HarnessQualityVerdict`
- **AND** the observation MUST NOT select retry, replan, repair, halt, completion, memory write, approval, or publication

#### Scenario: Candidate ports cannot self-authorize side effects

- **WHEN** a candidate-only memory, RAG, or legacy MCP port receives a write candidate, side-effect Tool request, caller boolean, or metadata claiming approval
- **THEN** the port MUST expose no direct generic memory commit capability and MUST fail closed for the side-effect Tool unless an exact Harness side-effect handler is bound
- **AND** only a durable Harness authorization derived from the frozen Graph binding, deterministic gate and Tool-policy evidence, budget, scope, attempt, and any required durable approval may invoke the canonical handler
- **AND** Artifact publication MUST continue through the retained artifact-owned port rather than becoming a worker leaf or being removed

#### Scenario: Planner returns a TaskPlan candidate

- **WHEN** a plan-builder LLM returns tasks, dependency hints, requested tools, and worker capability hints for a registered dynamic stage
- **THEN** Harness MUST validate the candidate against the frozen Graph, stage policy, registries, gates, and budgets before accepting a plan version
- **AND** the LLM MUST NOT choose an implementation, authorize a tool, dispatch a task, modify the Graph, or decide stage success

#### Scenario: TaskPlan scheduler reports ready tasks

- **WHEN** the internal TaskPlan scheduler calculates a stable set of ready tasks from accepted state
- **THEN** `HarnessControlPlane` MUST validate and durably commit each resulting dispatch decision before invoking a worker
- **AND** neither the queue nor a business service may activate additional tasks independently

### Requirement: Phase State Machine

Harness-managed Graph executable nodes SHALL advance through bounded `PLAN -> EXECUTE -> VERIFY` phases. For ordinary nodes, `PLAN` SHALL select and validate the controlled activity binding, `EXECUTE` SHALL call controlled workers, and `VERIFY` SHALL run deterministic gates before any Graph state transition is accepted. For an explicitly registered dynamic stage, `PLAN` SHALL build, validate, and durably accept an immutable TaskPlan version; `EXECUTE` SHALL schedule and collect only tasks from the accepted version; and `VERIFY` SHALL deterministically verify and aggregate task outputs before the Graph node succeeds. Every executable-node phase boundary SHALL be a checksum-bound durable record that carries the exact `GraphRunIdentity`, `node_id`, `node_instance_id`, attempt, strictly monotonic event sequence, closed phase/boundary values, canonical deterministic-gate evidence references, and UTC occurrence time. The record reader MUST reject moving Graph/compiler versions, missing node identity, unknown fields, legacy Workflow identity aliases, checksum tampering, and any mismatch between the record event sequence and its durable event envelope. The frozen outer Graph MUST NOT be modified by TaskPlan generation or replan.

#### Scenario: Node advances through all phases

- **WHEN** Harness runs a Graph executable node with valid inputs and an accepted worker result
- **THEN** the run transcript MUST record `PLAN`, `EXECUTE`, and `VERIFY` phase events in order
- **AND** each phase event MUST bind the same exact Graph checksum and node-instance identity used by the executing node
- **AND** the node MUST NOT publish final outputs before VERIFY passes

#### Scenario: Phase record identity or integrity is invalid

- **WHEN** a phase record lacks node identity, uses a moving Graph/compiler version or Workflow alias, has an unknown field, carries a non-monotonic event sequence, differs from its durable envelope sequence, or fails checksum verification
- **THEN** Harness recovery and projection MUST fail closed before accepting that phase transition
- **AND** no retry, replan, repair, successor activation, completion, memory write, or publication decision may be derived from the invalid record

#### Scenario: Dynamic stage accepts a plan before execution

- **WHEN** a dynamic stage receives a candidate that passes all deterministic plan gates
- **THEN** Harness MUST commit the accepted plan version and checksum during `PLAN` before any planned task is dispatched
- **AND** `EXECUTE` MUST use only that accepted plan or a later accepted patch version

#### Scenario: Dynamic task outputs require node VERIFY

- **WHEN** every required task reaches a successful committed result
- **THEN** Harness MUST enter the stage `VERIFY` phase and run the declared deterministic task and aggregation gates
- **AND** the Graph successor MUST NOT activate until the dynamic stage success transition commits

### Requirement: Controlled Failure Outcomes
When VERIFY fails or budgets are exhausted, Harness SHALL choose only explicit controlled outcomes: `replan`, `retry`, `route_to_repair`, `wait_for_approval`, `halted`, or `failed`. A Harness-managed stage MUST be considered safely halted only after its required terminal failure event is durably committed. If that commit fails, Harness MUST fail closed with a typed persistence outcome and MUST NOT report an ordinary `halted`, `blocked`, or business `failed` result.

#### Scenario: Budget exhaustion halts the run
- **WHEN** a Harness run exceeds `max_turns`, `max_replans`, `max_retries_per_step`, or `max_worker_calls`
- **THEN** Harness MUST transition the run to `halted`
- **AND** Harness MUST record the exhausted budget in the run transcript

#### Scenario: TaskPlan halt event cannot be committed
- **WHEN** a TaskPlan stage failure occurs and durable `TASK_PLAN_HALTED` persistence raises an error
- **THEN** Harness MUST return or raise `task_plan_halt_persistence_failed`
- **AND** Harness MUST NOT continue dispatch, aggregation, verification, publication, or report an ordinary terminal stage result

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
- **WHEN** a Graph contains activities with different declared quality gates
- **THEN** VERIFY MUST execute the current step's bound gate and framework mandatory gates in stable order
- **AND** Harness MUST NOT execute unrelated domain gates registered for other steps

#### Scenario: Gate execution raises an exception
- **WHEN** a required deterministic gate raises or returns an invalid result
- **THEN** Harness MUST record a stable failed gate outcome
- **AND** the scheduler MUST choose an allowed controlled failure outcome within the existing budgets

### Requirement: Subagent Isolation
Harness SHALL isolate subagents with independent context, private history, explicit handoff payloads, tool allowlists, memory namespaces, and versioned durable transcripts. Subagents MUST NOT read sibling transcripts, raw parent context, hidden prompts, unauthorized memory namespaces, or parent-scoped transcript queries. Every production subagent attempt MUST use an explicitly injected durable transcript store and MUST commit a readable checksum-bound transcript and candidate-output receipt before its result can be accepted; production MUST NOT implicitly construct a fake store.

#### Scenario: Cross-subagent data uses approved handoff
- **WHEN** one subagent output is needed by another subagent
- **THEN** Harness MUST serialize it through an approved handoff schema
- **AND** a gate MUST validate the handoff before the receiving subagent can consume it

#### Scenario: Production subagent attempt completes
- **WHEN** a production subagent returns a successful, failed, or halted candidate outcome
- **THEN** Harness MUST persist one typed attempt receipt bound to parent, child, Graph run, stage, task, task instance, attempt, and subagent identity
- **AND** the transcript gate MUST verify the receipt, body checksum, candidate-output checksum, and durable read-back before returning the outcome to TaskPlan verification

#### Scenario: Durable transcript persistence fails
- **WHEN** transcript commit, read-back, size validation, identity validation, or checksum verification fails
- **THEN** Harness MUST reject the original candidate outcome with a stable persistence reason
- **AND** it MUST record a controlled durable parent failure transition without falling back to process-local storage

### Requirement: Context Engineering Assembly

Harness SHALL assemble worker context from explicit stable prefix and dynamic tail sections. Global policy, pinned Graph route/condition table, schemas, gate definitions, tool allowlists, memory namespace policy, source refs, and budget values MUST NOT be compressed away or placed only in dynamic summaries.

#### Scenario: Critical control material survives compression

- **WHEN** context budget pressure requires compression
- **THEN** Harness MUST preserve policy, Graph route/condition, schema, gate, allowlist, namespace, source ref, and budget sections verbatim or through lossless references
- **AND** dynamic worker outputs MAY be summarized only outside the stable prefix

### Requirement: Bounded Agentic RAG
Harness SHALL control multi-round retrieval, source reads, verification, gap filling, and `RAGContextPack` assembly. RAG loops MUST declare `max_rounds`, `max_queries`, `max_source_reads`, `max_memory_hits`, and context budget.

#### Scenario: RAG loop stops at declared bounds
- **WHEN** a RAG worker requests additional retrieval after the configured limit is reached
- **THEN** Harness MUST stop retrieval
- **AND** Harness MUST record a bounded RAG outcome for VERIFY to evaluate

### Requirement: Trace Checkpoint Replay
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, artifact publication decisions, required subagent transcript/output receipts, and required terminal failure transitions to a durable transcript or event log that can support checkpointing and replay. Gate evidence MUST include the exact gate id and version, deterministic input reference, result reference, pass/fail outcome, stable reason code, aggregate verdict, and resulting scheduler decision before the next state or publication is accepted. Recovery MUST distinguish a durably committed terminal failure from an execution failure whose terminal evidence is absent or uncommitted. Required subagent evidence MUST be resolved and checksum-verified from durable storage without live worker execution.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, subagent receipt, and artifact decision events without calling an LLM

#### Scenario: Recovery resumes after committed VERIFY
- **WHEN** VERIFY evidence and its transition were durably committed before a process crash
- **THEN** recovery MUST use the recorded gate evidence and pinned gate version as scheduler input
- **AND** recovery MUST NOT replace the recorded verdict with current defaults or worker self-evaluation

#### Scenario: Recorded gate evidence is incomplete
- **WHEN** recovery cannot resolve the pinned gate version or verify the recorded gate evidence checksum
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST NOT guess, reclassify the history as passed, or invoke an LLM

#### Scenario: Terminal failure evidence is absent
- **WHEN** recovery observes TaskPlan execution evidence without the required durable `TASK_PLAN_HALTED` transition after a terminal failure
- **THEN** recovery MUST expose a controlled retry, quarantine, or manual-repair state
- **AND** it MUST NOT assume the stage safely halted or continue publication

#### Scenario: Offline replay resolves subagent evidence
- **WHEN** replay encounters a versioned TaskPlan result for a subagent attempt
- **THEN** it MUST resolve and verify the recorded transcript and candidate-output refs against the accepted attempt identity
- **AND** real subagent, tool, retrieval, memory-write, and publication call counts MUST remain zero

#### Scenario: Legacy subagent evidence is unavailable
- **WHEN** replay or inspection requires durable subagent evidence from a pre-v1 process-local transcript record
- **THEN** it MUST return the typed reason `subagent_transcript_legacy_unavailable`
- **AND** it MUST NOT manufacture a readable ref or treat the legacy string as verified evidence

### Requirement: Versioned Gate Binding

Harness SHALL resolve every declared Graph leaf activity quality gate to one exact deterministic gate id and version before recording run creation or invoking a worker. The registry MUST reject unknown gates, unversioned declarations, duplicate or ambiguous registrations, incompatible versions, missing dependencies, and dependency cycles.

#### Scenario: Unknown declared gate fails before execution

- **WHEN** a Graph activity declares `DefinitelyMissingGate@1`
- **THEN** Harness MUST reject the run before recording a worker call
- **AND** the run MUST NOT be reported as succeeded

#### Scenario: Gate dependency cannot be resolved

- **WHEN** a registered gate references a missing or cyclic deterministic dependency
- **THEN** Harness MUST fail closed during Graph preflight
- **AND** Harness MUST identify the invalid gate reference without executing any gate or worker

#### Scenario: Exact gate version is pinned

- **WHEN** a Graph activity declares `ClaimEvidenceGate@2`
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
- **THEN** Graph preflight MUST reject the Graph before worker execution

### Requirement: Durable Subagent Attempt Evidence
Harness SHALL own versioned immutable contracts for subagent context evidence, candidate output, transcript body, typed receipt, and a transcript store port. The production store SHALL atomically publish one run-scoped attempt bundle, SHALL support restart-safe read and verification, and SHALL enforce identical-body idempotency and different-body conflict semantics across threads, instances, and processes.

#### Scenario: Same attempt is committed twice
- **WHEN** two writers commit the same identity with the same context, output, and transcript checksums
- **THEN** both writes MUST return the original durable receipt
- **AND** the parent-scoped query MUST contain one transcript ref

#### Scenario: Same identity has different content
- **WHEN** a writer commits an existing attempt identity with a different document checksum
- **THEN** the store MUST fail with `subagent_transcript_conflict`
- **AND** it MUST leave the originally committed bundle unchanged and readable

#### Scenario: Stored bundle is tampered
- **WHEN** a body, ref, path, schema, size, identity field, or checksum no longer matches its receipt
- **THEN** read or verify MUST fail with a typed corrupt, not-found, size, or identity reason
- **AND** the evidence MUST NOT pass the transcript gate

#### Scenario: Receipt exists before parent result commit
- **WHEN** recovery finds a valid attempt receipt but no committed TaskPlan result
- **THEN** it MUST reconstruct the prior candidate outcome through a read-only recovery path
- **AND** it MUST NOT call the subagent worker or repeat a worker side effect

### Requirement: Bounded Subagent Evidence Content
Subagent transcripts SHALL contain only identity, schema/checksum, timestamps, approved refs, deterministic gate evidence, budget facts, bounded redaction facts, stable warning/error codes, and bounded lifecycle facts. The transcript MUST recursively reject private/raw fields and secret-like values, MUST default to at most `1 MiB`, and MUST reference rather than duplicate full candidate output.

#### Scenario: Transcript candidate contains private or secret content
- **WHEN** a transcript field contains a forbidden nested key or a secret-like credential value
- **THEN** transcript construction or persistence MUST fail closed
- **AND** no transcript body, log event, or metric payload may contain that value

#### Scenario: Transcript exceeds its size limit
- **WHEN** canonical transcript bytes exceed the configured production limit
- **THEN** persistence MUST fail with `subagent_transcript_size_exceeded`
- **AND** the store MUST NOT truncate the transcript and claim a complete receipt

#### Scenario: Parent transcripts are queried
- **WHEN** an authorized inspection service requests refs for one parent run with a bounded limit
- **THEN** the store MUST return a stable, deduplicated, parent-scoped ordering
- **AND** the query MUST NOT expose transcript bodies or refs from another parent run

### Requirement: Canonical Subagent Artifact Evidence

Harness SHALL resolve every non-empty artifact reference carried by a subagent candidate through an explicitly injected read-only canonical artifact verifier before accepting the candidate or replaying its TaskPlan history. Verification MUST enforce canonical reference syntax, accepted parent-run binding, manifest identity, declared size, checksum, and stored bytes; it MUST NOT return artifact payloads, grant publication visibility, invoke a worker, or create a competing artifact owner.

#### Scenario: Subagent artifact evidence is accepted

- **WHEN** a durable subagent output contains an artifact ref owned by the accepted parent run and the canonical verifier validates its manifest and bytes
- **THEN** TaskPlan MAY continue deterministic result verification
- **AND** the verifier MUST NOT publish the artifact or expose its payload to the subagent transcript reader

#### Scenario: Artifact evidence cannot be resolved

- **WHEN** a non-empty subagent artifact ref is malformed, missing, cross-run, stale, corrupt, or no canonical verifier is available
- **THEN** Harness MUST fail closed with a stable artifact-verification reason before committing a TaskResult
- **AND** the parent stage MUST record a durable controlled failure without falling back to string equality or process-local state

#### Scenario: Offline replay revalidates artifact evidence

- **WHEN** offline replay encounters a versioned subagent result with artifact refs
- **THEN** it MUST resolve those refs again through the canonical verifier using the recorded parent run identity
- **AND** live worker, tool, memory-write, retrieval, and publication call counts MUST remain zero

### Requirement: Control-plane state is Graph-native end to end

Harness SHALL use `HarnessGraphState` and exact Graph/node-instance contracts directly for run results, deterministic gate contexts, Wait registration/resume, approval causes, side-effect authorization, inspection and replay. The control plane MUST NOT project Graph state into a flat Workflow-shaped state model, synthesize legacy step identities, or retain a legacy-unbound lifecycle mode.

#### Scenario: Gate evaluates a Graph node

- **WHEN** an executable Graph node enters deterministic VERIFY
- **THEN** the gate receives the exact Graph run/checksum, node instance, attempt, accepted output and durable evidence refs
- **AND** no `_graph_compat_state`, flat step map or Workflow identity is constructed

#### Scenario: Approval resumes a Graph Wait

- **WHEN** an authorized approval cause matches the current durable Wait
- **THEN** Harness commits and evaluates it against Graph-native state and node-instance identity
- **AND** it does not synthesize a legacy waiting step or use a legacy lifecycle binding

### Requirement: Typed Leaf Activity Binding

Harness SHALL model Function, Tool, Skill, Subagent, and AgentLoop as explicit typed Graph leaf activity kinds. `HarnessGraphDefinition` SHALL checksum-bind every canonical leaf activity id to one exact worker reference, activity-contract reference, and leaf kind; composition SHALL independently register that exact tuple, and runtime resolution MUST verify the frozen selection, canonical worker type, exact implementation identities, versions, and required activity safety capabilities before dispatch. Every internal `TASK_PLAN` activity SHALL instead have one checksum-bound dynamic-stage declaration that pins its exact worker and activity references, policy reference, executable TaskPlan schema, required output roles, and complete exact support references. Internal `TASK_PLAN` stages MUST NOT be relabeled as one of the five leaf kinds, and the Graph compiler MUST NOT infer their bindings from metadata, registry defaults, aliases, or moving versions. `SCRIPT` MUST NOT silently satisfy Function, MCP transport MUST NOT silently satisfy Tool, and Artifact owner/runtime/storage MUST remain retained behind a Harness-authorized terminal publication port rather than becoming or being removed with a worker leaf.

#### Scenario: Exact typed leaf binding resolves

- **WHEN** an immutable GraphDefinition contains a checksum-valid, complete activity-to-leaf selection and the executable leaf requests the independently registered exact worker/activity pair with the same canonical leaf kind
- **THEN** Harness resolves the worker implementation and activity contract atomically
- **AND** missing or duplicate coverage, a different kind, wrong contract kind, unregistered pair, moving version, legacy alias, or Artifact-as-leaf declaration fails before dispatch

#### Scenario: Exact internal TaskPlan stage binding resolves

- **WHEN** an immutable GraphDefinition contains a `TASK_PLAN` activity and one checksum-valid dynamic-stage declaration with exact worker, activity, policy, schema, output-role, and support references
- **THEN** Graph preflight derives the stage step reference deterministically from the exact Graph identity/version and activity id and compiles all remaining fields only from that declaration
- **AND** missing, duplicate, unexpected, incomplete, inexact, metadata-inferred, leaf-aliased, or side-effect-owning TaskPlan stage bindings fail before `RUN_CREATED` or worker dispatch

#### Scenario: Worker result crosses Harness ingress

- **WHEN** any leaf worker returns candidate output, diagnostics, metrics, typed evidence, or candidate artifact refs
- **THEN** Harness reconstructs the complete strict worker-result contract without dropping typed evidence or refs
- **AND** unknown top-level fields and routing, gate, authorization, publication, memory-write, or persistence decisions are rejected before a durable result is accepted
