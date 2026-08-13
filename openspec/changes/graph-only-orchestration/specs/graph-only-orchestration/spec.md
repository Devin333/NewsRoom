## ADDED Requirements

### Requirement: Harness runs require an explicit Graph

每个 Harness run SHALL 在任何 `RUN_CREATED`、worker call 或外部 side effect 之前携带一个通过 preflight 的显式 Graph definition。缺少 Graph、Graph schema 未知、Graph 与 legacy declaration 并存或存在 legacy routing 字段时，系统 SHALL fail closed，并返回稳定的 typed validation reason。

#### Scenario: Missing Graph is rejected

- **WHEN** caller creates a run without `graph`
- **THEN** preflight returns `graph_required`
- **AND** no run-created event, worker call, checkpoint, artifact or publication side effect is recorded

#### Scenario: Legacy declaration is rejected

- **WHEN** caller submits `steps`, `entry_step_id`, `routing_rules`, `WorkflowSpec` or `graph=None` as the orchestration declaration
- **THEN** preflight returns `legacy_orchestration_not_supported`
- **AND** the system does not invoke a legacy compiler, runner or executor

#### Scenario: Valid Graph is pinned

- **WHEN** caller submits a valid versioned Graph definition
- **THEN** Harness records `graph_id`, `graph_version`, compiler version and canonical graph checksum before the first activity
- **AND** recovery and replay use that pinned Graph identity

### Requirement: Graph is the only outer control authority

Harness Graph control plane SHALL be the only component allowed to evaluate outer routing, node readiness, gate verdict, retry/replan/halt disposition, budget admission, wait resume, memory-write authorization, tool authorization and publication authorization. Workers, LLMs, AgentLoop, queues and interface services SHALL return candidate observations only.

#### Scenario: Worker suggests a route

- **WHEN** an activity output contains a suggested next node or quality verdict
- **THEN** Harness stores it as candidate evidence
- **AND** Graph evaluation ignores it as a control decision and uses pinned policy plus deterministic gate evidence

#### Scenario: AgentLoop requests approval

- **WHEN** AgentLoop returns a human-review candidate with an approval id
- **THEN** Harness creates the durable Graph Wait registration and decides whether the node waits
- **AND** AgentLoop does not resume, route or publish by itself

### Requirement: Graph responsibilities have explicit owners before deletion

在删除任何旧 Workflow module 前，系统 SHALL have an inventory row that records the old symbol/module, production callers, replacement owner, data contract, migration phase, verification command and deletion disposition. A replacement SHALL not import the retired module or expose a forwarding compatibility facade。

#### Scenario: Unowned deletion candidate

- **WHEN** an inventory row has no replacement owner or caller count is nonzero
- **THEN** the deletion gate blocks removal
- **AND** the old module remains unchanged until the missing evidence is supplied

#### Scenario: Reusable artifact responsibility is moved

- **WHEN** artifact manifest or integrity behavior is needed after caller migration
- **THEN** the artifact-owned service provides the contract directly
- **AND** no caller imports `framework.workflow.runtime` merely to obtain that behavior

### Requirement: Historical Workflow records migrate offline

历史 manifests、events、checkpoints、replay bundles、artifact indexes 和 cursor refs SHALL be converted only by a versioned offline migrator operating on a read-only snapshot. The migrator SHALL never invoke an old executor, worker, LLM, Tool, retrieval, memory write or publication path。

#### Scenario: Convertible record is migrated

- **WHEN** a legacy record has a known schema, complete identity, valid paths and sufficient deterministic evidence
- **THEN** the migrator writes a Graph record with preserved checksums, sequence and source provenance
- **AND** a rerun with the same source checksum is idempotent

#### Scenario: Record cannot be converted

- **WHEN** a record has unknown schema, missing evidence, invalid path or ambiguous identity
- **THEN** it is placed in a read-only quarantine manifest with a stable reason code
- **AND** resume, replay execution and publication are rejected for that record

### Requirement: Graph persistence and replay are self-contained

Graph run manifests, durable events, checkpoints, artifact index records and replay bundles SHALL reference Graph identity and exact schema/compiler/gate versions. Offline replay SHALL consume recorded decisions and evidence without invoking live workers or legacy runtime code。

#### Scenario: Graph run is inspected

- **WHEN** an authorized inspection service reads a completed Graph run
- **THEN** it resolves the pinned Graph manifest, node-instance outputs, gate evidence and artifact refs
- **AND** it does not load Workflow runner/executor modules

#### Scenario: Replay evidence is incomplete

- **WHEN** replay cannot verify a pinned Graph version or recorded evidence checksum
- **THEN** replay returns a typed history diagnostic and fails closed
- **AND** it does not guess a route or call a live worker

### Requirement: Graph operations own pause and resume

Cancel, signal, approval decision, wait timeout, inspection and replay requests SHALL enter through Harness Graph application services. Interface adapters SHALL validate public input and call those services; they SHALL NOT select a node, mutate Graph state, call an executor, or write a checkpoint directly。

#### Scenario: Approval decision resumes a Graph

- **WHEN** an authorized approval decision references a valid Graph Wait and checksum-bound checkpoint
- **THEN** the application service submits a typed resume intent to Harness
- **AND** the Graph reducer decides the next node activation and records the transition durably

#### Scenario: Resume identity is invalid

- **WHEN** approval, signal or checkpoint identity does not match the pinned Graph run
- **THEN** the service rejects the request before state mutation
- **AND** no activity or publication is started

### Requirement: Workflow retirement has a zero-reference completion gate

The Graph-only cutover SHALL be considered complete only when active production source, public exports, registries, reflection names, canonical active specs and supported tests contain no retired Workflow runtime symbol or import. Any remaining legacy reader or fixture SHALL be explicitly allowlisted as offline migration evidence and SHALL not be importable by production runtime。

#### Scenario: Retired symbol remains in production

- **WHEN** repository architecture scans find `framework.workflow`, `WorkflowRunner`, `WorkflowExecutor`, `HarnessWorkflowSpec`, `compile_legacy` or an equivalent registry entry in active production paths
- **THEN** the release gate fails
- **AND** deletion/cutover is not complete

#### Scenario: Final scan contains only historical evidence

- **WHEN** scans find legacy names only in a signed migration report, archived OpenSpec or isolated migration fixture
- **THEN** the gate records the exact allowlist and passes the source/runtime check
- **AND** production imports remain zero
