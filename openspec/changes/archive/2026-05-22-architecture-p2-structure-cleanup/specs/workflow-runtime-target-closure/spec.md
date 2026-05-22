## ADDED Requirements

### Requirement: Workflow spec compatibility is preserved
The system SHALL preserve existing workflow spec import compatibility while keeping canonical spec models outside workflow runtime implementation modules.

#### Scenario: Existing workflow spec import
- **WHEN** callers import workflow skill step spec compatibility paths
- **THEN** imports continue to resolve without changing workflow execution behavior
