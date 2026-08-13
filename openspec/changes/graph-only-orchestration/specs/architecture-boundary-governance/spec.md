## REMOVED Requirements

### Requirement: Framework specs do not depend on workflow runtime

**Reason**：仅禁止 framework specs 导入旧 runtime 已不足以表达 Graph-only 最终边界，且旧 requirement 名称继续把 Workflow runtime 当作一个存在的架构对象。

**Migration**：以新的 `Framework specs do not depend on orchestration implementation` requirement 接管 domain-neutral model 隔离，并由 `Retired Workflow boundaries remain closed` 覆盖旧 package、exports、registries 和动态加载。

## ADDED Requirements

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
