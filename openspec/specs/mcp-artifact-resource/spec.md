# mcp-artifact-resource Specification

## Purpose
TBD - created by archiving change mcp-artifact-resource. Update Purpose after archive.
## Requirements
### Requirement: MCP reads run artifact resources
The system SHALL read manifest-listed run artifacts through strict artifact inspection before returning resource content.

#### Scenario: Existing verified run artifact
- **WHEN** `news://runs/{run_id}/artifacts/{artifact_key}` is read and expected checksum verification succeeds
- **THEN** the result contains the artifact detail returned by the artifact inspection service

#### Scenario: Existing artifact is tampered
- **WHEN** the resource artifact bytes do not match valid expected metadata
- **THEN** the resource returns no artifact content

### Requirement: MCP artifact reads fail safely
The system SHALL return a safe MCP resource failure with stable typed error information when an artifact cannot be read or verified.

#### Scenario: Missing artifact
- **WHEN** a missing artifact key is requested
- **THEN** the MCP resource result is unsuccessful and includes the underlying error type and message

#### Scenario: Artifact integrity fails
- **WHEN** strict artifact inspection raises `ArtifactChecksumMismatchError`, `ArtifactStoreMetadataError`, `ArtifactStoreRequiredError`, or `ArtifactPathError`
- **THEN** the MCP resource result has `success=False`, no data, and the same class name in `error_type`

#### Scenario: MCP HTTP receives failed artifact result
- **WHEN** an MCP artifact result has `success=False`
- **THEN** the HTTP adapter returns an outer failure envelope with the fixed 400, 409, or 500 mapping instead of HTTP 200 success

### Requirement: Structured artifact content is redacted
The system SHALL redact sensitive fields when structured artifact content is read.

#### Scenario: Sensitive JSON field
- **WHEN** a JSON or JSONL artifact contains a field such as `token`, `api_key`, `password`, or `secret`
- **THEN** the returned artifact content replaces the sensitive value with `[redacted]`
