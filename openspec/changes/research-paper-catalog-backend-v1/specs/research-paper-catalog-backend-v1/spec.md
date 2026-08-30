## ADDED Requirements

### Requirement: Sources resolve to traceable paper identities
The system SHALL create a source snapshot before merging a paper identity, preserve external identifiers and versions, and record field conflicts with provenance.

#### Scenario: Equivalent sources merge
- **WHEN** arXiv, DOI and publisher inputs expose the same external identifier or explainable title/author/year fingerprint
- **THEN** the inputs resolve to one canonical paper id
- **AND** each input remains a separate source snapshot
- **AND** the merge reason and field provenance are retained

#### Scenario: Restricted source is metadata-only
- **WHEN** a source denies or cannot provide the full text
- **THEN** the result status is `metadata_only`
- **AND** no parsed document is claimed
- **AND** the access diagnostic identifies the denial or failure

### Requirement: ParsePaper is the single application ingest contract
The system SHALL expose `ParsePaperRequest`, `ParsePaperResult` and `ParsePaperUseCase` with bounded synchronous execution, explicit statuses and durable phase events.

#### Scenario: PDF fallback is observable
- **WHEN** a configured structured parser fails or fails the deterministic quality probe
- **THEN** every parser attempt and reason is persisted
- **AND** the next parser is tried within the retry budget
- **AND** a terminal text fallback is marked `degraded` when structure is unavailable

#### Scenario: Duplicate ingest is idempotent
- **WHEN** the same canonical identity and source checksum are ingested again in the same actor scope
- **THEN** the existing paper, relations and artifacts are reused
- **AND** no duplicate entities or relations are created

### Requirement: Catalog uses typed relations and provenance
The Catalog SHALL represent paper-to-task/method/dataset/benchmark/metric/score/code-repository links as typed relations carrying confidence, status, source snapshot refs and evidence refs.

#### Scenario: Relation is stored as a candidate
- **WHEN** extraction proposes a relation without sufficient deterministic verification
- **THEN** the relation status is `candidate`
- **AND** the relation includes its source and evidence references
- **AND** it is queryable without being presented as verified

### Requirement: Benchmark publication is deterministic and protocol-aware
The system SHALL keep candidate or conflicting scores out of verified leaderboards and SHALL require compatible metric direction, dataset version, split, unit, protocol and evidence before verification.

#### Scenario: Candidate score is excluded
- **WHEN** a score has status `candidate`, `conflicting`, missing evidence, or incompatible protocol
- **THEN** it is excluded from leaderboard results
- **AND** its diagnostic remains queryable

### Requirement: Interfaces use application services
HTTP routers and CLI commands SHALL call application services and SHALL expose shared status, error, provenance and artifact reference fields while enforcing actor/tenant scope.

#### Scenario: Parse endpoint returns a durable run
- **WHEN** an authorized client posts a parse request
- **THEN** the response includes a durable `run_id`, canonical `paper_id` when resolved, status and provenance/artifact references
- **AND** parser or storage adapters are not invoked directly by the router
