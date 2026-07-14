# run-replay-api Specification

## Purpose
TBD - created by archiving change run-replay-api. Update Purpose after archive.
## Requirements
### Requirement: API exposes run replay
The system SHALL expose read-only run replay bundles through the HTTP API.

#### Scenario: Replay exists
- **WHEN** `GET /api/v1/runs/{run_id}/replay` is called
- **THEN** the response includes the replay bundle in the standard API envelope

### Requirement: API maps replay errors
The system SHALL map replay lookup and validation failures to stable API errors.

#### Scenario: Run is missing
- **WHEN** replay is requested for a missing run
- **THEN** the API returns `run_not_found`
