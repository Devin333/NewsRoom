## ADDED Requirements

### Requirement: Built-in artifact tool searches current-run artifacts
The system SHALL provide an `artifact.search` tool that discovers artifacts
within the current run directory and returns lightweight artifact refs.

#### Scenario: Artifact path or content matches query
- **WHEN** `artifact.search` receives a query
- **THEN** ToolExecutor returns matching artifact refs without full content

#### Scenario: Unsafe path prefix is provided
- **WHEN** `artifact.search` receives an absolute or parent-traversal prefix
- **THEN** ToolExecutor fails the call before scanning outside the run directory
