## MODIFIED Requirements

### Requirement: Built-in artifact tool searches current-run artifacts
The system SHALL provide an `artifact.search` tool that discovers artifacts only within the canonical validated current run directory and returns lightweight artifact refs.

#### Scenario: Artifact path or content matches query
- **WHEN** `artifact.search` receives a query and a valid path prefix
- **THEN** ToolExecutor returns matching artifact refs without full content

#### Scenario: Unsafe path prefix is provided
- **WHEN** `artifact.search` receives an absolute, drive-relative, UNC/device, parent-traversal, reserved, ADS, DOS-device, trailing-dot/space, or linked external prefix
- **THEN** ToolExecutor fails the call before scanning outside the run directory

#### Scenario: Unsafe run identifier is provided
- **WHEN** `artifact.search` is configured with an unsafe run identifier
- **THEN** ToolExecutor fails before resolving or scanning a run directory
