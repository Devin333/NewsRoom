## MODIFIED Requirements

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

### Requirement: Context Engineering Assembly

Harness SHALL assemble worker context from explicit stable prefix and dynamic tail sections. Global policy, pinned Graph route/condition table, schemas, gate definitions, tool allowlists, memory namespace policy, source refs, and budget values MUST NOT be compressed away or placed only in dynamic summaries.

#### Scenario: Critical control material survives compression

- **WHEN** context budget pressure requires compression
- **THEN** Harness MUST preserve policy, Graph route/condition, schema, gate, allowlist, namespace, source ref, and budget sections verbatim or through lossless references
- **AND** dynamic worker outputs MAY be summarized only outside the stable prefix

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
