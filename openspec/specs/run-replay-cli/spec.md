# run-replay-cli Specification

## Purpose
TBD - created by archiving change run-replay-cli. Update Purpose after archive.
## Requirements
### Requirement: Run inspection builds replay bundles
The system SHALL build a read-only replay bundle from real persisted run artifacts.

#### Scenario: Run artifacts exist
- **WHEN** replay is requested for a run
- **THEN** the result includes manifest, events, and artifact entries

### Requirement: Replay output redacts sensitive fields
The system SHALL redact sensitive keys from replay events and JSON artifacts.

#### Scenario: Artifact contains an API key field
- **WHEN** replay is generated
- **THEN** the sensitive value is replaced with a redacted marker

### Requirement: CLI exposes run replay
The system SHALL expose run replay through the CLI.

#### Scenario: Run replay is requested
- **WHEN** `news runs replay <run_id> --json` is run
- **THEN** the command prints a machine-readable replay bundle
