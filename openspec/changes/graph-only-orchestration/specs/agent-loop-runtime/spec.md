## REMOVED Requirements

### Requirement: WorkflowRunner resumes from approval context

**Reason**：外层暂停/恢复权威迁移到 Harness Graph Wait、checkpoint reducer 和 application service；保留 `WorkflowRunner` 会继续维护第二套执行器。

**Migration**：approval service 验证 Graph run、Wait node 和 checksum-bound checkpoint 后提交 typed resume intent，由 Harness Graph 决定 node activation；接口使用 Graph 版本化 resume surface。

## MODIFIED Requirements

### Requirement: Approval decisions provide resume context

The system SHALL provide a standard Graph resume context for decided approval records so callers can resume a paused Graph Wait with explicit node-scoped updates. The context MUST include Graph run identity, Graph checkpoint identity, approval metadata, and only validated update keys.

#### Scenario: Approved decision produces Graph resume intent

- **WHEN** an approval request has an approved decision
- **THEN** the approval service returns a resume context containing a Graph run id, Graph checkpoint ref, a node-scoped update keyed by the requested decision key, and compact approval metadata

#### Scenario: Pending approval cannot produce resume context

- **WHEN** an approval request has no recorded decision
- **THEN** the approval service rejects Graph resume context creation for that approval

#### Scenario: Graph resume records approval metadata

- **WHEN** a Graph is resumed from a checkpoint with approval resume metadata
- **THEN** the Graph resume event and run manifest include that metadata
