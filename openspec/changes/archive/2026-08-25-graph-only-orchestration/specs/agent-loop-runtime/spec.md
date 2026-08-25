## REMOVED Requirements

### Requirement: WorkflowRunner resumes from approval context

**Reason**：外层暂停/恢复权威迁移到 Harness Graph Wait、checkpoint reducer 和 application service；保留 `WorkflowRunner` 会继续维护第二套执行器。

**Migration**：approval service 验证 current Graph run、durable Wait scope、approval evidence 和 actor identity 后提交 typed approval cause；cause durable commit 后由 Harness Graph 自动推进并决定 node activation，接口不提交 state patch 或 routing intent。

## MODIFIED Requirements

### Requirement: Approval decisions provide resume context

The system SHALL provide bounded read-only Graph Wait and approval context for decided approval records. Callers SHALL submit only the approval decision identity; they SHALL NOT resume a Graph with node updates, checkpoint overrides, resume metadata, or routing intent.

#### Scenario: Approved decision produces typed approval cause

- **WHEN** an approval request has an approved decision
- **THEN** the approval service resolves the current Graph run and durable Wait scope, then submits checksum-bound approval evidence as a typed cause
- **AND** Harness durably commits the cause before automatically resuming Graph evaluation

#### Scenario: Pending approval cannot produce resume context

- **WHEN** an approval request has no recorded decision
- **THEN** the approval service rejects Graph resume context creation for that approval

#### Scenario: Graph resume records approval evidence

- **WHEN** Harness resumes evaluation after accepting an approval cause
- **THEN** the durable Graph history records the approval evidence reference, actor scope and exact Wait scope without caller-supplied state patches
