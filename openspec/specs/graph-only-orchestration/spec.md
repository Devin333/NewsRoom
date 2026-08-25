# graph-only-orchestration Specification

## Purpose
Record the Graph-only orchestration cutover and its fail-closed legacy boundary.

## Requirements
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

### Requirement: Graph-only cutover is one-way

The change SHALL replace the live Workflow declaration, compiler, reader, writer, runtime route and public surface directly with their Graph-only owners. Repository implementation and legacy deletion SHALL NOT depend on a rollback point, rollback drill, managed-environment sign-off, observation window, prerequisite-change archive or a second runtime path. The cutover MUST NOT introduce a feature flag, dual writer/reader, fallback executor or forwarding compatibility facade.

#### Scenario: Graph production authority is installed

- **WHEN** replacement owner contracts and scope-matched automated tests are present
- **THEN** the production caller, writer, reader and runtime route switch to Graph-only authority in the same coherent implementation boundary
- **AND** the replaced Workflow path is not retained as a fallback

#### Scenario: Legacy runtime deletion is requested

- **WHEN** production callers are zero and replacement tests prove the Graph-owned behavior
- **THEN** the legacy reader, writer, runtime, public export and canonical requirement are deleted without requiring rollback evidence
- **AND** Artifact owner/runtime/storage/publication capabilities remain intact

### Requirement: Historical Workflow records are not executable

Historical Workflow manifests, events, checkpoints, replay bundles, artifact indexes and cursor refs SHALL NOT be converted or interpreted by the live Graph runtime. A bounded history-only reader MAY classify an isolated record for audit, but it SHALL NOT be importable from production composition and SHALL never invoke an old executor, worker, LLM, Tool, retrieval, memory write or publication path.

#### Scenario: Legacy record reaches a live Graph reader

- **WHEN** a live reader receives a Workflow schema, identity alias or legacy orchestration record
- **THEN** it returns a stable typed quarantine or `legacy_orchestration_not_supported` diagnostic
- **AND** resume, replay execution, worker dispatch and publication are rejected

#### Scenario: Legacy record is retained for audit

- **WHEN** an isolated historical fixture or raw record must remain available for audit
- **THEN** it is retained outside production runtime imports with its source checksum and quarantine reason
- **AND** it grants no migration, recovery or execution authority

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

### Requirement: Framework-wide orchestration identity is Graph-only

All live framework contracts that carry outer orchestration identity SHALL use an exact, versioned Graph run identity and, where applicable, node-instance or stage identity. This includes control-plane state/results/gates/Waits, SubAgent invocation and transcripts, Event/Trace propagation, RAG/Context, Memory/Governance, Worker task/results, Skill context, LLM structured-output policy, tool metrics, checkpoints and replay. A nullable `workflow_id`, Workflow scope enum, `workflow_run_id`, legacy schema default or Graph-to-flat-state projection SHALL NOT remain as a live compatibility alias.

#### Scenario: Graph state reaches a gate or side-effect handler

- **WHEN** Harness constructs a gate context, Wait cause, side-effect request, run result or inspection view
- **THEN** the contract binds the exact Graph run, Graph checksum and required node-instance identity directly
- **AND** it does not construct or consume a flat Workflow-shaped `HarnessState`

#### Scenario: Framework carrier contains a Workflow alias

- **WHEN** an Event, Trace, RAG/Context, Memory, Governance, Worker, Skill, LLM or Tool contract contains a Workflow identity or scope alias
- **THEN** the live major reader rejects it before persistence, dispatch, gate evaluation or side effect
- **AND** it does not silently discard, null, translate or dual-write the alias

### Requirement: Live schema readers have one Graph major

Production writers, readers, stores, registries and root exports SHALL expose only the current Graph-only major schema for each active contract. Older SubAgent, Event, checkpoint, replay or orchestration schemas MAY be recognized only by isolated history-only tooling that is not reachable from production composition; active readers SHALL NOT branch between legacy and Graph authority.

#### Scenario: Legacy SubAgent transcript reaches production recovery

- **WHEN** production recovery receives a v1/v2 Workflow-shaped SubAgent invocation, transcript, receipt or bundle
- **THEN** recovery returns a stable unsupported-history diagnostic before worker dispatch or store mutation
- **AND** only the current Graph-only SubAgent major is accepted by the live reader/store

#### Scenario: Workflow event schema is registered as current

- **WHEN** the active Event schema catalog or reflection registry contains a current Workflow event/operation schema or old Event facade
- **THEN** the architecture and schema gates fail
- **AND** Graph event/read-model contracts remain the only live registration

### Requirement: Artifact authority survives Workflow retirement

The cutover SHALL retain `framework/harness/artifacts` as the owner of Graph terminal manifests, integrity, catalog, governance, quota, usage, GC, cost, inspection, storage and publication. It SHALL also retain any still-used `ArtifactManager` raw storage, integrity and path-safety primitives. Only Workflow-specific artifact refs, publishers, readers and leaf classifications SHALL be deleted.

#### Scenario: Legacy Artifact publisher is removed

- **WHEN** `WorkflowArtifactRef`, `WorkflowArtifactPublisher`, `LocalArtifactPublisher` or their tests/exports have no production caller
- **THEN** those Workflow bridges are deleted
- **AND** Graph terminal publication, inspection, lifecycle and governance tests continue to pass through the artifact owner

### Requirement: Graph operations own Wait causes and automatic resume

Cancel, signal, approval decision, wait timeout, inspection and replay requests SHALL enter through Harness Graph application services. Interface adapters SHALL validate public input and call those services; they SHALL NOT select a node, mutate Graph state, call an executor, or write a checkpoint directly。

#### Scenario: Approval decision resumes a Graph

- **WHEN** an authorized approval decision resolves to the current durable Graph Wait scope
- **THEN** the application service submits a typed approval cause to Harness
- **AND** Harness durably commits the cause before automatically resuming evaluation
- **AND** the Graph reducer exclusively decides the next node activation and records the transition durably

#### Scenario: Resume identity is invalid

- **WHEN** approval or signal identity does not match the current durable Wait scope and pinned Graph run
- **THEN** the service rejects the request before state mutation
- **AND** no activity or publication is started

### Requirement: Workflow retirement has a zero-reference completion gate

The Graph-only cutover SHALL be considered complete only when active production source, public exports, registries, reflection names, canonical active specs and supported tests contain no retired Workflow runtime symbol or import. Any remaining legacy reader or fixture SHALL be explicitly allowlisted as offline migration evidence and SHALL not be importable by production runtime。

#### Scenario: Retired symbol remains in production

- **WHEN** repository architecture scans find `framework.workflow`, `WorkflowRunner`, `WorkflowExecutor`, `HarnessWorkflowSpec`, `compile_legacy` or an equivalent registry entry in active production paths
- **THEN** the release gate fails
- **AND** deletion/cutover is not complete

#### Scenario: Unused root Workflow facade is retired before package cutover

- **WHEN** a legacy declaration, compiler, reader, routing or transition-registry name has zero production callers through `framework.harness`
- **THEN** the root import, attribute and `__all__` re-export are removed and architecture tests prevent their restoration
- **AND** tests that still verify the transitional contract import its concrete legacy owner instead of treating the root facade as supported compatibility API
- **AND** any remaining production caller of `framework.harness.workflow` keeps final package deletion and task completion open
- **AND** retained Artifact owner ports remain public and are not removed with Workflow orchestration exports

#### Scenario: Final scan contains only historical evidence

- **WHEN** scans find legacy names only in a signed migration report, archived OpenSpec or isolated migration fixture
- **THEN** the gate records the exact allowlist and passes the source/runtime check
- **AND** production imports remain zero
