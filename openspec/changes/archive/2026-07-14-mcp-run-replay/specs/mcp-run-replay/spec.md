## ADDED Requirements

### Requirement: MCP exposes run replay tool
The system SHALL expose run replay as an MCP tool backed by the run inspection service.

#### Scenario: Tool is called
- **WHEN** `news.run.replay` is called with a run id
- **THEN** the result includes the replay bundle

### Requirement: MCP exposes run replay resource
The system SHALL expose run replay as an MCP resource backed by the run inspection service.

#### Scenario: Resource is read
- **WHEN** `news://runs/{run_id}/replay` is read
- **THEN** the result includes the replay bundle
