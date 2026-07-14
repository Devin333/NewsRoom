## MODIFIED Requirements

### Requirement: Artifact inspection reads manifest-listed artifacts
The system SHALL list and read only artifacts referenced by a run manifest whose run identifier and relative paths resolve as canonical descendants of the configured artifact root.

#### Scenario: Artifact list is requested
- **WHEN** a valid run manifest contains valid artifact entries
- **THEN** the service returns artifact summaries with key, relative path, content type, and size

#### Scenario: Inspection path is unsafe
- **WHEN** a run identifier or manifest artifact path is traversal, absolute, drive-relative, UNC/device, linked outside the root, or otherwise invalid
- **THEN** inspection fails before reading content outside the configured artifact root

### Requirement: CLI can inspect artifacts
The system SHALL expose `news artifacts list` and `news artifacts show` with JSON output support and fail nonzero for unsafe artifact paths.

#### Scenario: CLI artifact show JSON
- **WHEN** a valid artifact is shown with `--json`
- **THEN** the command prints artifact metadata and parsed content

#### Scenario: CLI artifact input is unsafe
- **WHEN** artifact inspection receives an unsafe run identifier or artifact path
- **THEN** the command prints a sanitized error, returns a nonzero exit code, and does not print artifact content

### Requirement: API can inspect artifacts
The system SHALL expose artifact list and detail endpoints through the common API envelope and distinguish invalid paths from missing artifacts.

#### Scenario: Artifact is missing
- **WHEN** a valid but missing artifact key is requested
- **THEN** the API returns a unified `artifact_not_found` error with HTTP 404

#### Scenario: Artifact path is invalid
- **WHEN** an unsafe run identifier or manifest artifact path is requested
- **THEN** the API returns HTTP 400 with an invalid artifact/run path code and does not read external content
