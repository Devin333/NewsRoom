## ADDED Requirements

### Requirement: Acceptance Service
The interface layer SHALL expose an offline acceptance service that verifies final business runtime surfaces plus board, cross-board, weekly, persistence, and eval readiness.

#### Scenario: Final acceptance returns checks
- **WHEN** final business acceptance is invoked with offline fixtures
- **THEN** it returns an AcceptanceResult containing named checks for final surface, raw payload safety, board workflows, cross-board graph, feedback, learning, policy, regression, artifacts, and serialization

### Requirement: CLI Acceptance Command
The CLI SHALL expose `news business acceptance --final` and preserve existing acceptance modes.

#### Scenario: Final acceptance JSON output
- **WHEN** `news business acceptance --final --json` is invoked
- **THEN** it prints the serialized AcceptanceResult without directly calling board workflow or runner internals

### Requirement: Artifact Contract Acceptance
Final business run artifact references SHALL be serializable and include board_type, run_id, and artifact_type metadata without forbidden raw or secret fields.

#### Scenario: Artifact references validate
- **WHEN** a final business run is built
- **THEN** artifact refs are present, serializable, and aligned with final run metadata counts

### Requirement: Cross-board Runtime Acceptance
Final business runtime SHALL expose cross-board graph nodes, scored paths, and scored insights.

#### Scenario: Cross-board graph validates
- **WHEN** a final business run is built
- **THEN** graph nodes, paths, insights, and scoring metadata are present and serializable

### Requirement: Weekly Runtime Acceptance
Weekly intelligence SHALL run from local fixture reports and publish core and enhanced outputs offline.

#### Scenario: Weekly fixture run validates
- **WHEN** weekly acceptance runs against persisted fixture reports
- **THEN** final_report, report_markdown, weekly_metrics, and enhanced weekly outputs are present

### Requirement: Proposal Persistence Acceptance
The local JSON improvement proposal store SHALL persist proposal state transitions across instances.

#### Scenario: Proposal status survives reload
- **WHEN** proposals are saved, approved, rejected, or marked applied
- **THEN** a new store instance reads the expected status and status filtering works

### Requirement: Eval Suite Acceptance
The board eval suite SHALL contain at least twenty cases with at least five cases per primary board and expose pass_rate.

#### Scenario: Eval suite validates
- **WHEN** the eval suite is run offline
- **THEN** each result has metrics, no unhandled errors occur, and failures include reasons

### Requirement: Raw Payload Safety
Final business public output SHALL NOT expose forbidden raw or secret field names.

#### Scenario: Final public surfaces are sanitized
- **WHEN** final business run output is serialized
- **THEN** raw_payload, raw_content, raw_html, full_text, secret, api_key, and token field names are absent from final public surfaces
