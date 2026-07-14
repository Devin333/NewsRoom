## MODIFIED Requirements

### Requirement: API exposes run replay
The system SHALL expose read-only run replay bundles through the HTTP API only after strict integrity preflight succeeds.

#### Scenario: Replay exists and verifies
- **WHEN** `GET /api/v1/runs/{run_id}/replay` is called for a verified run
- **THEN** the response includes the replay bundle in the standard API envelope

#### Scenario: Replay integrity fails
- **WHEN** any non-manifest replay artifact fails checksum or metadata verification
- **THEN** the API returns an error envelope without replay artifact content

### Requirement: API maps replay errors
The system SHALL map replay lookup, validation, checksum, metadata, and verification-configuration failures to stable API errors.

#### Scenario: Run is missing
- **WHEN** replay is requested for a missing run
- **THEN** the API returns `run_not_found` with HTTP 404

#### Scenario: Replay checksum mismatches
- **WHEN** strict replay detects mismatched artifact bytes
- **THEN** the API returns HTTP 409 with `artifact_checksum_mismatch`

#### Scenario: Replay metadata is corrupt
- **WHEN** strict replay detects missing or invalid expected integrity metadata
- **THEN** the API returns HTTP 409 with `artifact_metadata_corrupt`

#### Scenario: Replay verification store is unavailable
- **WHEN** replay verification requires an unavailable store
- **THEN** the API returns HTTP 500 with `artifact_store_unavailable`
