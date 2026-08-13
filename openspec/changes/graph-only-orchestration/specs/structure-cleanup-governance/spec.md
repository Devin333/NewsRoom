## REMOVED Requirements

### Requirement: Workflow specs compatibility facade

**Reason**：Graph-only cutover explicitly rejects `framework.workflow.specs` compatibility imports。

**Migration**：仍有价值的 leaf/domain-neutral models 迁到其真实 owner，所有调用方直接导入 owner contract；不保留 facade。

## MODIFIED Requirements

### Requirement: Root export surfaces are guarded

The system SHALL keep reviewed root package exports stable while preventing unreviewed export-surface growth and preventing any retired Workflow runtime compatibility export.

#### Scenario: Export guard test

- **WHEN** package export guard tests run
- **THEN** required Graph/domain-neutral names exist and unexpected growth is flagged
- **AND** `WorkflowRunner`, `WorkflowExecutor`, legacy `RunResult`, `HarnessWorkflowSpec` and Workflow facade modules are absent
