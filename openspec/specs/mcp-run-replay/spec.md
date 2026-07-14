# mcp-run-replay Specification

## Purpose
TBD - created by archiving change mcp-run-replay. Update Purpose after archive.
## Requirements
### Requirement: MCP exposes run replay tool
The system SHALL expose strict run replay as an MCP tool backed by the run inspection service.

#### Scenario: Tool replay verifies
- **WHEN** `news.run.replay` is called with a run whose artifacts verify
- **THEN** the result is successful and includes the replay bundle

#### Scenario: Tool replay fails integrity
- **WHEN** strict replay raises a typed checksum, metadata, path, or store-required error
- **THEN** the tool result has `success=False`, no replay data, and the exception class name in `error_type`

### Requirement: MCP exposes run replay resource
The system SHALL expose strict run replay as an MCP resource backed by the run inspection service.

#### Scenario: Resource replay verifies
- **WHEN** `news://runs/{run_id}/replay` is read for a verified run
- **THEN** the result is successful and includes the replay bundle

#### Scenario: Resource replay fails integrity
- **WHEN** strict replay raises a typed checksum, metadata, path, or store-required error
- **THEN** the resource result has `success=False`, no replay data, and the exception class name in `error_type`
