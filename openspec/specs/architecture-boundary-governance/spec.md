# architecture-boundary-governance Specification

## Purpose
TBD - created by archiving change architecture-p0-boundary-hardening. Update Purpose after archive.
## Requirements
### Requirement: Framework specs do not depend on orchestration implementation

The system SHALL keep framework specification and domain-neutral model packages free of imports from Graph control-plane implementation modules. The retired `framework.workflow` package SHALL not exist or be exported from any active package.

#### Scenario: Status terminal checks

- **WHEN** callers evaluate activity or Graph terminal status from domain-neutral models
- **THEN** the result is computed without importing `framework.harness.control_plane`
- **AND** no import or fallback to `framework.workflow` is possible

### Requirement: Retired Workflow boundaries remain closed

Architecture tests SHALL fail when active production code imports, exports, registers, dynamically loads or reconstructs the retired Workflow runtime or Harness Workflow declaration namespace.

#### Scenario: Compatibility facade is introduced

- **WHEN** a module re-exports a retired Workflow symbol from a Graph implementation
- **THEN** the architecture gate fails even if the symbol delegates to working Graph code

#### Scenario: Registry references a retired runner by string

- **WHEN** a runner/activity registry contains `WorkflowRunner`, `WorkflowExecutor`, `AgentLoopStepRunner` or an equivalent retired handler name
- **THEN** the architecture gate fails

#### Scenario: Horizontal framework contract retains Workflow authority

- **WHEN** active control-plane, SubAgent, Event/Trace, RAG/Context, Memory/Governance, Worker, Skill, LLM, Tool metric, checkpoint/replay or Artifact bridge code exposes a Workflow identity, scope, current schema, fallback reader or compatibility projection
- **THEN** the architecture gate fails with the exact module and symbol
- **AND** history-only fixtures remain allowed only through a narrow explicit non-production allowlist

#### Scenario: Legacy Event or migration facade is production importable

- **WHEN** production composition can import an old Event/EventEnvelope facade, Workflow schema registration, active migrator or legacy checkpoint/replay reader
- **THEN** the dependency-topology gate fails even if no current request calls that path

### Requirement: Skill Runtime ownership is explicit
The system SHALL keep Skill Runtime implementation under `framework.skills` and prevent business, infrastructure, or interface imports from entering that package.

#### Scenario: Skill Runtime boundary test
- **WHEN** architecture boundary tests inspect Skill Runtime imports
- **THEN** forbidden layer imports are reported as failures

### Requirement: Infrastructure memory dependency debt is tracked
The system SHALL explicitly list current infrastructure modules that depend on business memory models until a port/DTO migration removes them.

#### Scenario: Known debt visibility
- **WHEN** architecture tests inspect infrastructure memory and graph modules
- **THEN** only listed legacy dependency paths are allowed

### Requirement: Business research does not depend on interface layers
The system SHALL keep `business/research` free of direct imports from `interfaces`, including business-owned RAG evaluation CLIs.

#### Scenario: Live answer eval uses business-owned assembly
- **WHEN** `run_evidence_eval --live-answer-eval` runs with parsed paper chunks from `--papers-dir`
- **THEN** the live answer ask callable is assembled from business-owned RAG session components without importing `interfaces`
- **AND** answer evaluation receives gated Harness payload semantics for conversion into `EvidenceAnswerSample`

#### Scenario: Live answer eval without fixture chunks fails closed
- **WHEN** `run_evidence_eval --live-answer-eval` is requested without parsed fixture chunks and no outer-layer ask callable is injected
- **THEN** the command fails with a clear configuration error instead of importing `interfaces` or production stores from `business/research`

### Requirement: Workflow dependency freeze is subtract-only during migration

Before final zero-reference retirement, architecture tests SHALL compare active production Workflow imports, exports, registry/reflection symbols, and legacy schema writers against a reviewed machine-readable baseline. The gate SHALL fail on every new or broadened dependency. A migrated baseline entry SHALL be removed and SHALL NOT be re-added or replaced by a compatibility facade.

#### Scenario: A new legacy dependency is introduced

- **WHEN** active production code adds a Workflow import, retired runner/export symbol, registry/reflection entry, or legacy schema writer not present in the reviewed baseline
- **THEN** the architecture gate fails with the exact source location and dependency kind

#### Scenario: An existing dependency is migrated

- **WHEN** a caller moves to its Graph or domain-neutral owner and its legacy dependency disappears
- **THEN** the baseline row is removed in the same verified slice
- **AND** later reintroduction of the same dependency fails the gate
