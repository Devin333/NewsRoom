## ADDED Requirements

### Requirement: Board Workflow Stage Outcomes
Board workflows SHALL record stage-level outcomes for each execution stage.

#### Scenario: Successful run includes stage results
- **WHEN** a board workflow runs successfully
- **THEN** result metadata includes workflow execution with each configured stage

### Requirement: Failed Stage Recording
Board workflows SHALL record failed stage metadata before re-raising exceptions.

#### Scenario: Pipeline exception records failed stage
- **WHEN** a workflow stage raises an exception
- **THEN** the failed stage is recorded with error details and block recovery action
