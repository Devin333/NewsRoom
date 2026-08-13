## REMOVED Requirements

### Requirement: Versioned Workflow Graph Compilation

**Reason**：Graph compiler contract 迁入新 `harness-graph` capability，旧名称同时承载 Workflow identity，会在 canonical specs 中保留错误的外层模型。

**Migration**：使用 `harness-graph` 的 `Versioned Graph Compilation`，并把 persisted identity 迁为 `graph_id`/`graph_version`。

### Requirement: Supported Graph Constructs

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管，控制构造不得成为 worker。

### Requirement: Deterministic Choice Definitions

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管，Choice 继续只读 deterministic evidence。

### Requirement: Parallel Graph Definitions

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 branch/join/failure policy。

### Requirement: Bounded Loop Definitions

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 bounded cycle policy。

### Requirement: Durable Wait Definitions

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 signal/timer/approval Wait contract。

### Requirement: Explicit Compensation Definitions

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 explicit compensation bindings。

### Requirement: Parallel Output Isolation

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 node-instance output isolation 和 deterministic merge。

### Requirement: Graph Preflight Validation

**Reason**：该 Graph requirement 迁入新 `harness-graph` capability。

**Migration**：由 `harness-graph` 同名 requirement 接管 fail-closed preflight。

### Requirement: Legacy Workflow Graph Compilation

**Reason**：前置 `harness-workflow-graph-runtime` 的 bounded migration 已完成后，legacy `HarnessWorkflowSpec` compiler 会继续保留第二套 outer declaration authority；Graph-only cutover 要求显式 Graph 是唯一 runtime 输入。

**Migration**：在该前置 change 归档后，将本 delta rebase 到 canonical `harness-workflow-graph` spec；所有 Research 和其他 caller 先改为显式 Graph definition，legacy history 由独立 offline migrator 处理，不能由 live compiler fallback。
