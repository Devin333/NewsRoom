# harness-graph Specification

## Purpose
Define the versioned Graph DSL, deterministic compilation, control constructs, repair and compensation topology, durable Waits, and Graph preflight boundary.

## Requirements
### Requirement: Versioned Graph Compilation

The system SHALL compile every Harness Graph definition into one immutable normalized graph with an explicit graph schema version, graph identity and version, stable node and edge ordering, exact activity/handler references, and a canonical graph checksum before recording `RUN_CREATED`. Before compilation, the definition SHALL prove an exact activity topology closure: every root `StepRef`, compensation activity and repair activity resolves to one declared activity, and every declared activity is used by at least one of those topology classes. Every ordinary executable activity SHALL be selected through its checksum-bound typed leaf declaration. Every internal `TASK_PLAN` activity SHALL instead be selected through a distinct checksum-bound stage declaration containing exact worker, activity, policy, executable schema, required output-role, and complete support references. The compiler SHALL derive the exact step reference deterministically from Graph identity/version and activity id, and SHALL NOT infer any implementation or TaskPlan authority from metadata, registry defaults, aliases, or moving versions.

#### Scenario: Explicit Graph DSL is compiled

- **WHEN** a Graph definition declares supported Graph DSL constructs and valid activity references
- **THEN** preflight produces one normalized graph with stable identities and checksum
- **AND** runtime execution reads only the pinned normalized graph

#### Scenario: Dynamic stage declaration is incomplete

- **WHEN** a Graph definition contains a `TASK_PLAN` activity without exactly one complete, exact, checksum-bound stage declaration
- **THEN** preflight rejects the Graph before `RUN_CREATED`
- **AND** it does not relabel the stage as a leaf or recover missing values from activity metadata or registry defaults

#### Scenario: Definition activity topology is incomplete

- **WHEN** a root, compensation or repair reference names an undeclared activity, or a declared activity is unused by all three topology classes
- **THEN** Graph definition admission fails closed with a stable activity-topology diagnostic before compilation
- **AND** repair-only and compensation-only activities remain valid when they are explicitly referenced
- **AND** the compiler neither invents a missing activity nor silently drops an unused declaration

#### Scenario: Graph changes after run creation

- **WHEN** Graph code or configuration changes after a run has recorded its graph checksum
- **THEN** recovery continues only with the pinned compatible Graph version or an explicit offline migration
- **AND** it does not silently execute the changed Graph

### Requirement: Supported Graph Constructs

The Graph definition SHALL support `Sequence`, `Choice`, `Parallel-All`, `Parallel-Any`, `Bounded-Loop`, `Wait`, and explicit `Repair` and `Compensation` bindings. Control constructs SHALL compile to deterministic Graph policy and MUST NOT be represented as LLM, Tool, AgentLoop or business worker calls.

#### Scenario: Sequence contains executable activities

- **WHEN** a Sequence contains three executable activity references
- **THEN** the normalized graph records dependencies that require each predecessor to succeed before its successor becomes ready
- **AND** it does not create a fake worker for the Sequence construct

#### Scenario: Unknown Graph construct is declared

- **WHEN** a Graph uses an unregistered construct or node kind
- **THEN** preflight rejects the Graph before `RUN_CREATED`

### Requirement: Explicit Graph Repair Topology

Repair routing SHALL be declared only by checksum-bound `HarnessGraphRepairBinding` records owned by `HarnessGraphDefinition`. Every binding SHALL pin a unique binding id, one exact executable source node id from the root Graph, one independent repair node id, one registered repair activity id, and a non-empty unique trigger set containing only `worker_failure_after_retry_exhaustion` and/or `verification_failure`. Repair node ids MUST NOT collide with root or other repair node ids, and one `(source_node_id, trigger)` MUST NOT resolve to multiple repair targets. GraphDefinition activities MUST NOT carry `HarnessRetryPolicy.repair_step_id`; the compiler and scheduler MUST NOT infer repair topology from leaf metadata, activity names, worker outputs, aliases, or registry defaults.

#### Scenario: Repair topology is explicit

- **WHEN** a Graph definition declares one repair binding from an executable source node to a registered repair activity with exact trigger semantics
- **THEN** the definition checksum includes the binding and its deterministic identities
- **AND** the future Graph compiler can emit one unambiguous repair node and route without reading leaf-owned routing metadata

#### Scenario: Leaf activity declares a repair target

- **WHEN** any GraphDefinition activity carries a non-empty `retry_policy.repair_step_id`
- **THEN** the Graph definition is rejected before compilation or `RUN_CREATED`
- **AND** no repair edge is inferred from that leaf field

#### Scenario: Repair binding is ambiguous

- **WHEN** repair bindings reuse a repair node id, reference an unknown source or repair activity, collide with a root node id, use an unsupported trigger, or map one source trigger to multiple targets
- **THEN** Graph definition validation fails closed with a stable diagnostic

### Requirement: Deterministic Choice Definitions

A Choice SHALL use only versioned restricted structural conditions over allowed Harness inputs, verified outputs, node status, and deterministic gate results. Branches SHALL have stable priority, SHALL declare at most one default, and MUST NOT evaluate arbitrary code or worker route suggestions.

#### Scenario: Multiple Choice conditions match

- **WHEN** more than one declared branch condition matches the same accepted state
- **THEN** the branch with the explicitly higher stable priority is selected
- **AND** container iteration order does not affect the result

#### Scenario: Choice has no matching branch

- **WHEN** no branch condition matches and no default exists
- **THEN** execution produces a typed `no_matching_route` outcome
- **AND** no successor is activated

#### Scenario: Worker suggests a Choice branch

- **WHEN** a worker output contains a suggested branch or route
- **THEN** Graph evaluation ignores that suggestion as a control input
- **AND** selects only from the pinned condition policy and accepted Harness state

### Requirement: Parallel Graph Definitions

Parallel-All and Parallel-Any SHALL declare explicit branch scopes and matching join policy. Parallel-All SHALL declare `fail_fast`, `wait_all`, or `compensate` failure policy, and Parallel-Any SHALL declare cancellation and aggregate-failure policy.

#### Scenario: Parallel-All definition is complete

- **WHEN** a Parallel-All construct has uniquely scoped branches, one matching join, and a supported failure policy
- **THEN** the compiler emits paired fork and join control nodes with deterministic branch order

#### Scenario: Parallel fork has no valid join

- **WHEN** a Parallel construct has an ambiguous, missing, or multiply paired join
- **THEN** preflight rejects the Graph before any branch activity runs

### Requirement: Bounded Loop Definitions

Every runtime cycle SHALL be introduced by a `Bounded-Loop` construct with a positive static `max_iterations`, a restricted deterministic continuation condition, and an explicit exit or exhaustion path. All other cycles SHALL be invalid.

#### Scenario: Loop has a positive bound

- **WHEN** a Bounded-Loop declares `max_iterations=3` and valid condition and exit edges
- **THEN** the compiler emits a loop guard and versioned bound that recovery can resolve

#### Scenario: Undeclared Graph cycle exists

- **WHEN** Graph edges form a cycle outside a compiled Bounded-Loop
- **THEN** preflight rejects the Graph as unbounded

### Requirement: Durable Wait Definitions

A Wait SHALL declare a supported versioned kind, correlation contract, scope requirements, and timeout or explicit unlimited-wait policy. Supported kinds SHALL include signal, timer, and approval.

#### Scenario: Signal Wait is valid

- **WHEN** a signal Wait declares signal schema version, correlation key source, tenant and identity scope, and timeout policy
- **THEN** the compiler records an exact durable Wait contract in the Graph

#### Scenario: Wait has an ambiguous correlation contract

- **WHEN** a Wait omits required scope, signal identity, or correlation information
- **THEN** preflight rejects the Graph before registration or execution

### Requirement: Explicit Compensation Definitions

Automatic compensation SHALL be available only for an effectful executable node with an exact versioned compensation binding and compatible identity, subject, idempotency, and authorization scopes.

#### Scenario: Effectful node declares compensation

- **WHEN** an effectful node references a registered compensation activity or handler with exact version
- **THEN** preflight pins that binding to the normalized graph
- **AND** records the relationship in the graph checksum

#### Scenario: Compensation is inferred from a worker type

- **WHEN** an effectful node has no explicit compensation binding
- **THEN** the Graph MUST NOT infer an inverse operation from worker type, output, or naming

#### Scenario: Terminal publication declares compensation

- **WHEN** a Graph declares a `terminal_run` compensation binding
- **THEN** its originating effectful node handler MUST exactly match the terminal side-effect policy handler
- **AND** the Graph pins one unambiguous compensation handler and activity version

#### Scenario: Terminal publication has no exact compensation binding

- **WHEN** a terminal side-effect outcome commits without a matching `terminal_run` binding
- **THEN** the outcome remains durable but MUST NOT be added to the automatic compensation stack
- **AND** the runtime MUST NOT infer an inverse operation

### Requirement: Parallel Output Isolation

Parallel branches SHALL write to node-instance-scoped output namespaces by default. Concurrent writes to one shared key SHALL fail preflight unless an explicit deterministic merge contract resolves them; last-writer-wins SHALL NOT be a supported merge policy.

#### Scenario: Branches write the same shared key

- **WHEN** two potentially concurrent branches declare the same shared output key without a merge contract
- **THEN** preflight rejects the Graph with a stable output-conflict diagnostic

#### Scenario: Join declares a deterministic merge

- **WHEN** a join declares an ordered pure merge or a verified aggregation activity over exact branch output references
- **THEN** the Graph records that merge contract and may expose the merged output after the join

### Requirement: Graph Preflight Validation

Graph preflight SHALL validate identities, endpoint references, reachability, terminal paths, control pairing, allowed cycles, loop bounds, Choice defaults and priorities, input producers, output conflicts, condition paths and operators, graph size limits, and exact worker, gate, side-effect, and compensation references before recording a run. The Graph-owned preflight SHALL accept only an exact-schema `NormalizedHarnessGraph`; it MUST NOT own or invoke a Workflow compiler, accept `HarnessWorkflowSpec`, import the legacy Workflow namespace, or execute a transitional legacy compilation path before validation.

#### Scenario: Graph contains multiple structural defects

- **WHEN** a Graph contains unreachable terminal nodes, an unsupported condition path, and an unresolved gate reference
- **THEN** preflight fails with deterministic bounded diagnostics
- **AND** records no `RUN_CREATED` event or worker activity

#### Scenario: Legacy compiler is unavailable to Graph preflight

- **WHEN** a Workflow declaration reaches run admission
- **THEN** the control plane returns `legacy_orchestration_not_supported` before Graph preflight or `RUN_CREATED`
- **AND** it does not invoke a transitional compiler, `prepare(workflow)` method, Workflow import or legacy package re-export

### Requirement: Legacy declarations are not Graph inputs

The Graph compiler SHALL accept only explicit Graph definitions. It SHALL NOT compile ordered Workflow steps, entry-step declarations, routing rules, Workflow constructors or legacy Workflow schema records into an executable Graph at runtime.

#### Scenario: Legacy Workflow declaration reaches preflight

- **WHEN** preflight receives a legacy Workflow declaration rather than an explicit Graph definition
- **THEN** it returns `legacy_orchestration_not_supported`
- **AND** no normalized graph or run record is created

#### Scenario: Legacy history reaches Graph runtime

- **WHEN** a known legacy record is presented for live inspection, resume or replay execution
- **THEN** the Graph runtime returns a typed quarantine diagnostic and never invokes a legacy compiler
- **AND** any retained raw fixture remains history-only and outside production imports
