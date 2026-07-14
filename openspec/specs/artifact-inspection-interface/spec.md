# artifact-inspection-interface Specification

## Purpose
TBD - created by archiving change artifact-inspection-interface. Update Purpose after archive.
## Requirements
### Requirement: Artifact inspection reads manifest-listed artifacts
The system SHALL list only canonical manifest-listed artifact paths and SHALL return artifact content only after strict expected-checksum verification.

#### Scenario: Artifact list is requested
- **WHEN** a valid run manifest contains valid artifact entries
- **THEN** the service returns artifact summaries with key, relative path, content type, and size

#### Scenario: Inspection path is unsafe
- **WHEN** a run identifier or manifest artifact path is traversal, absolute, drive-relative, UNC/device, linked outside the root, or otherwise invalid
- **THEN** inspection fails before reading content outside the configured artifact root

#### Scenario: Artifact content is tampered
- **WHEN** direct artifact detail is requested and persisted bytes do not match valid expected metadata
- **THEN** inspection raises `ArtifactChecksumMismatchError` and returns no content

### Requirement: CLI can inspect artifacts
The system SHALL expose `news artifacts list` and `news artifacts show` with JSON output support and SHALL fail with exit code `1` on typed path, checksum, metadata, or store-configuration failures.

#### Scenario: CLI artifact show JSON
- **WHEN** a verified artifact is shown with `--json`
- **THEN** the command prints artifact metadata and parsed content

#### Scenario: CLI artifact integrity fails
- **WHEN** artifact inspection receives unsafe input, mismatched bytes, corrupt metadata, or unavailable verification configuration
- **THEN** the command prints a sanitized error to stderr, returns exit code `1`, and does not print artifact content

### Requirement: API can inspect artifacts
The system SHALL expose artifact list and detail endpoints through the common API envelope and SHALL distinguish invalid paths, missing artifacts, corrupt artifacts, and unavailable verification configuration.

#### Scenario: Artifact is missing
- **WHEN** a valid but missing artifact key is requested
- **THEN** the API returns a unified `artifact_not_found` error with HTTP 404

#### Scenario: Artifact path is invalid
- **WHEN** an unsafe run identifier or manifest artifact path is requested
- **THEN** the API returns HTTP 400 with an invalid artifact/run path code and does not read external content

#### Scenario: Artifact integrity conflicts
- **WHEN** checksum comparison fails or expected metadata is corrupt
- **THEN** the API returns HTTP 409 with the stable integrity error code and no artifact content

#### Scenario: Integrity store is unavailable
- **WHEN** verification requires a store that is not configured
- **THEN** the API returns HTTP 500 with `artifact_store_unavailable`
