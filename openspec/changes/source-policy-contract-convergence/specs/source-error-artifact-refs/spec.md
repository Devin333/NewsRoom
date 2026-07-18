## MODIFIED Requirements

### Requirement: Source error artifacts link to fetch diagnostics
The system SHALL include request and response artifact refs on persisted Source
error artifacts when matching fetch diagnostics exist. Connector construction,
the interface SourceError mapper, serialization, and artifact projection SHALL
preserve explicit refs without coercion or replacement.

#### Scenario: Source fetch fails with matching diagnostics
- **WHEN** a workflow writes Source fetch request, fetch result, and Source error
  artifacts for the same Source fetch attempt
- **THEN** the Source error artifact payload includes `request_ref`
- **AND** the Source error artifact payload includes `response_ref`
- **AND** the matching `source_artifacts/index.json` error entry includes the
  same `request_ref` and `response_ref`

#### Scenario: Explicit refs survive infrastructure mapping
- **GIVEN** an infrastructure SourceError contains explicit object or mapping
  refs for its request and response
- **WHEN** the interface mapper converts it to the business SourceError and the
  artifact writer serializes it
- **THEN** object mapping preserves both ref values and representations
- **AND** JSON serialization equals each ref's canonical mapping representation

### Requirement: Source errors carry fetch request ids
A request-aware Source connector adapter SHALL annotate connector Source errors
with the fetch request id for the call that produced the error, and shared error
construction, mapping, and artifact publication SHALL preserve that id. Direct
connector calls without request context SHALL NOT invent an id.

#### Scenario: Daily source collection records a partial fetch failure
- **WHEN** one Source fails and another Source succeeds in the same run
- **THEN** the failed Source error metadata includes the failed fetch
  `request_id`
- **AND** the failed Source entry can be joined to the matching fetch result
  record by `request_id`

#### Scenario: Request id survives connector and mapper boundaries
- **WHEN** a connector creates a SourceError for a failed fetch request
- **THEN** the shared factory records its `request_id`
- **AND** the interface mapper and artifact projection preserve the same value

#### Scenario: Concurrent request contexts remain isolated
- **WHEN** one connector adapter handles concurrent failed requests
- **THEN** each SourceError carries only the request id from its own call
- **AND** no request context is stored on shared connector mutable state
