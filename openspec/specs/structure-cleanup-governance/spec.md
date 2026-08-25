# structure-cleanup-governance Specification

## Purpose
TBD - created by archiving change architecture-p2-structure-cleanup. Update Purpose after archive.
## Requirements
### Requirement: Source scans exclude Python cache artifacts
The system SHALL keep generated Python cache artifacts out of source-controlled architecture scans.

#### Scenario: Repository file scan
- **WHEN** architecture tooling scans source directories
- **THEN** `__pycache__` artifacts do not appear as source modules

### Requirement: Retired Workflow spec facade remains absent
The system SHALL keep canonical activity and Graph spec ownership outside the retired Workflow namespace and SHALL reject compatibility imports from `framework.workflow.specs`.

#### Scenario: Legacy SkillStepSpec import
- **WHEN** callers import `SkillStepSpec` from `framework.workflow.specs`
- **THEN** the import fails with the documented legacy-orchestration diagnostic
- **AND** no forwarding compatibility facade is installed

### Requirement: Root export surfaces are guarded

The system SHALL keep reviewed root package exports stable while preventing unreviewed export-surface growth and preventing any retired Workflow runtime compatibility export.

#### Scenario: Export guard test

- **WHEN** package export guard tests run
- **THEN** required Graph/domain-neutral names exist and unexpected growth is flagged
- **AND** `WorkflowRunner`, `WorkflowExecutor`, legacy `RunResult`, `HarnessWorkflowSpec` and Workflow facade modules are absent

### Requirement: Architecture documentation indexes exist
The system SHALL provide lightweight indexes for framework improvement docs, skill docs, and OpenSpec specs.

#### Scenario: Documentation navigation
- **WHEN** developers inspect architecture documentation folders
- **THEN** an index explains current, historical, and follow-up content boundaries
