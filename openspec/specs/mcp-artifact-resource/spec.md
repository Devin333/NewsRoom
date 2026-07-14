# mcp-artifact-resource Specification

## Purpose
TBD - created by archiving change mcp-artifact-resource. Update Purpose after archive.
## Requirements
### Requirement: MCP reads run artifact resources
The system SHALL read manifest-listed run artifacts through MCP resources.

#### Scenario: Existing run artifact
- **WHEN** `news://runs/{run_id}/artifacts/{artifact_key}` is read
- **THEN** the result contains the artifact detail returned by the artifact inspection service

### Requirement: MCP artifact reads fail safely
The system SHALL return a safe MCP resource error when an artifact resource cannot be read.

#### Scenario: Missing artifact
- **WHEN** a missing artifact key is requested
- **THEN** the MCP resource result is unsuccessful and includes the underlying error type and message

### Requirement: Structured artifact content is redacted
The system SHALL redact sensitive fields when structured artifact content is read.

#### Scenario: Sensitive JSON field
- **WHEN** a JSON or JSONL artifact contains a field such as `token`, `api_key`, `password`, or `secret`
- **THEN** the returned artifact content replaces the sensitive value with `[redacted]`
