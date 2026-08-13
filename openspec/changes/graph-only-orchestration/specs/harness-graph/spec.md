## ADDED Requirements

### Requirement: Versioned Graph Compilation

The system SHALL compile every Harness Graph definition into one immutable normalized graph with an explicit graph schema version, graph identity and version, stable node and edge ordering, exact activity/handler references, and a canonical graph checksum before recording `RUN_CREATED`.

#### Scenario: Explicit Graph DSL is compiled

- **WHEN** a Graph definition declares supported Graph DSL constructs and valid activity references
- **THEN** preflight produces one normalized graph with stable identities and checksum
- **AND** runtime execution reads only the pinned normalized graph

#### Scenario: Graph changes after run creation

- **WHEN** Graph code or configuration changes after a run has recorded its graph checksum
- **THEN** recovery continues only with the pinned compatible Graph version or an explicit offline migration
- **AND** it does not silently execute the changed Graph

### Requirement: Supported Graph Constructs

The Graph DSL SHALL support `Sequence`, `Choice`, `Parallel-All`, `Parallel-Any`, `Bounded-Loop`, `Wait`, and explicit `Compensation` bindings. Control constructs SHALL compile to deterministic Graph policy and MUST NOT be represented as LLM, Tool, AgentLoop or business worker calls.

#### Scenario: Sequence contains executable activities

- **WHEN** a Sequence contains three executable activity references
- **THEN** the normalized graph records dependencies that require each predecessor to succeed before its successor becomes ready
- **AND** it does not create a fake worker for the Sequence construct

#### Scenario: Unknown Graph construct is declared

- **WHEN** a Graph uses an unregistered construct or node kind
- **THEN** preflight rejects the Graph before `RUN_CREATED`

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

Graph preflight SHALL validate identities, endpoint references, reachability, terminal paths, control pairing, allowed cycles, loop bounds, Choice defaults and priorities, input producers, output conflicts, condition paths and operators, graph size limits, and exact worker, gate, side-effect, and compensation references before recording a run.

#### Scenario: Graph contains multiple structural defects

- **WHEN** a Graph contains unreachable terminal nodes, an unsupported condition path, and an unresolved gate reference
- **THEN** preflight fails with deterministic bounded diagnostics
- **AND** records no `RUN_CREATED` event or worker activity

### Requirement: Legacy declarations are not Graph inputs

The Graph compiler SHALL accept only explicit Graph definitions. It SHALL NOT compile ordered Workflow steps, entry-step declarations, routing rules, Workflow constructors or legacy Workflow schema records into an executable Graph at runtime.

#### Scenario: Legacy Workflow declaration reaches preflight

- **WHEN** preflight receives a legacy Workflow declaration rather than an explicit Graph definition
- **THEN** it returns `legacy_orchestration_not_supported`
- **AND** no normalized graph or run record is created

#### Scenario: Legacy history requires conversion

- **WHEN** a known legacy record must be retained for inspection or replay
- **THEN** a separate offline migration tool converts it before the Graph runtime reads it
- **AND** the Graph runtime never invokes a legacy compiler
