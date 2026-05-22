## ADDED Requirements

### Requirement: Source scans exclude Python cache artifacts
The system SHALL keep generated Python cache artifacts out of source-controlled architecture scans.

#### Scenario: Repository file scan
- **WHEN** architecture tooling scans source directories
- **THEN** `__pycache__` artifacts do not appear as source modules

### Requirement: Workflow specs compatibility facade
The system SHALL preserve `framework.workflow.specs.SkillStepSpec` imports while canonical spec ownership is clarified outside workflow runtime internals.

#### Scenario: Legacy SkillStepSpec import
- **WHEN** callers import `SkillStepSpec` from `framework.workflow.specs`
- **THEN** the import resolves to the canonical spec class

### Requirement: Root export surfaces are guarded
The system SHALL keep root package compatibility exports available while preventing unreviewed export-surface growth.

#### Scenario: Export guard test
- **WHEN** package export guard tests run
- **THEN** required compatibility names exist and unexpected growth is flagged

### Requirement: Architecture documentation indexes exist
The system SHALL provide lightweight indexes for framework improvement docs, skill docs, and OpenSpec specs.

#### Scenario: Documentation navigation
- **WHEN** developers inspect architecture documentation folders
- **THEN** an index explains current, historical, and follow-up content boundaries
