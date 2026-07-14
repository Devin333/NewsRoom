## ADDED Requirements

### Requirement: Artifact inspection reads manifest-listed artifacts
The system SHALL list and read only artifacts referenced by a run manifest under the configured artifact root.

#### Scenario: Artifact list is requested
- **WHEN** a run manifest contains artifact entries
- **THEN** the service returns artifact summaries with key, relative path, content type, and size

### Requirement: CLI can inspect artifacts
The system SHALL expose `news artifacts list` and `news artifacts show` with JSON output support.

#### Scenario: CLI artifact show JSON
- **WHEN** an artifact is shown with `--json`
- **THEN** the command prints artifact metadata and parsed content

### Requirement: API can inspect artifacts
The system SHALL expose artifact list and detail endpoints through the common API envelope.

#### Scenario: Artifact is missing
- **WHEN** a missing artifact key is requested
- **THEN** the API returns a unified `artifact_not_found` error with HTTP 404
