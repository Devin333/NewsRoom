# run-replay-cli Specification

## Purpose
TBD - created by archiving change run-replay-cli. Update Purpose after archive.
## Requirements
### Requirement: Run inspection builds replay bundles
The system SHALL build a read-only replay bundle from real persisted run artifacts only after every non-manifest artifact passes strict integrity preflight.

#### Scenario: Run artifacts verify
- **WHEN** replay is requested for a run whose non-manifest artifacts match valid expected checksums
- **THEN** the result includes manifest, events, and artifact entries

#### Scenario: Replay artifact fails integrity
- **WHEN** any non-manifest artifact is missing expected integrity metadata, has corrupt metadata, or has mismatched bytes
- **THEN** replay fails as a whole without returning any artifact content

### Requirement: Replay output redacts sensitive fields
The system SHALL redact sensitive keys from replay events and JSON artifacts.

#### Scenario: Artifact contains an API key field
- **WHEN** replay is generated
- **THEN** the sensitive value is replaced with a redacted marker

### Requirement: CLI exposes run replay
The system SHALL expose strict run replay through the CLI and SHALL return exit code `1` for typed path, checksum, metadata, or store-configuration failures.

#### Scenario: Run replay is requested
- **WHEN** `news runs replay <run_id> --json` is run for a verified run
- **THEN** the command prints a machine-readable replay bundle

#### Scenario: Run replay integrity fails
- **WHEN** strict replay encounters a typed integrity failure
- **THEN** the command prints a sanitized error to stderr, returns exit code `1`, and prints no replay artifact content
