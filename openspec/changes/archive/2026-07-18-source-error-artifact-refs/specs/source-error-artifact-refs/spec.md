## ADDED Requirements

### Requirement: Source error artifacts link to fetch diagnostics
The system SHALL include request and response artifact refs on persisted source
error artifacts when matching fetch diagnostics exist.

#### Scenario: Source fetch fails with matching diagnostics
- **WHEN** a workflow writes source fetch request, fetch result, and source
  error artifacts for the same source fetch attempt
- **THEN** the source error artifact payload includes `request_ref`
- **AND** the source error artifact payload includes `response_ref`
- **AND** the matching `source_artifacts/index.json` error entry includes the
  same `request_ref` and `response_ref`

### Requirement: Source errors carry fetch request ids
The source collection workflow SHALL annotate connector source errors with the
fetch request id for the attempt that produced the error.

#### Scenario: Daily source collection records a partial fetch failure
- **WHEN** one source fails and another source succeeds in the same run
- **THEN** the failed source error metadata includes the failed fetch
  `request_id`
- **AND** the failed source entry can be joined to the matching fetch result
  record by `request_id`
