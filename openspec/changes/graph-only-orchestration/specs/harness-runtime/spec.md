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

#### Scenario: Planner returns a TaskPlan candidate

- **WHEN** a plan-builder LLM returns tasks, dependency hints, requested tools, and worker capability hints for a registered dynamic stage
- **THEN** Harness MUST validate the candidate against the frozen Graph, stage policy, registries, gates, and budgets before accepting a plan version
- **AND** the LLM MUST NOT choose an implementation, authorize a tool, dispatch a task, modify the Graph, or decide stage success

#### Scenario: TaskPlan scheduler reports ready tasks

- **WHEN** the internal TaskPlan scheduler calculates a stable set of ready tasks from accepted state
- **THEN** `HarnessControlPlane` MUST validate and durably commit each resulting dispatch decision before invoking a worker
- **AND** neither the queue nor a business service may activate additional tasks independently

### Requirement: Phase State Machine

Harness-managed Graph executable nodes SHALL advance through bounded `PLAN -> EXECUTE -> VERIFY` phases. For ordinary nodes, `PLAN` SHALL select and validate the controlled activity binding, `EXECUTE` SHALL call controlled workers, and `VERIFY` SHALL run deterministic gates before any Graph state transition is accepted. For an explicitly registered dynamic stage, `PLAN` SHALL build, validate, and durably accept an immutable TaskPlan version; `EXECUTE` SHALL schedule and collect only tasks from the accepted version; and `VERIFY` SHALL deterministically verify and aggregate task outputs before the Graph node succeeds. The frozen outer Graph MUST NOT be modified by TaskPlan generation or replan.

#### Scenario: Node advances through all phases

- **WHEN** Harness runs a Graph executable node with valid inputs and an accepted worker result
- **THEN** the run transcript MUST record `PLAN`, `EXECUTE`, and `VERIFY` phase events in order
- **AND** the node MUST NOT publish final outputs before VERIFY passes

#### Scenario: Dynamic stage accepts a plan before execution

- **WHEN** a dynamic stage receives a candidate that passes all deterministic plan gates
- **THEN** Harness MUST commit the accepted plan version and checksum during `PLAN` before any planned task is dispatched
- **AND** `EXECUTE` MUST use only that accepted plan or a later accepted patch version

#### Scenario: Dynamic task outputs require node VERIFY

- **WHEN** every required task reaches a successful committed result
- **THEN** Harness MUST enter the stage `VERIFY` phase and run the declared deterministic task and aggregation gates
- **AND** the Graph successor MUST NOT activate until the dynamic stage success transition commits

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
