## MODIFIED Requirements

### Requirement: Workflow runs populate the artifact index
The system SHALL index artifacts produced by local workflow runs only after their run identifier and manifest paths resolve within the canonical artifact root.

#### Scenario: Workflow run completes
- **WHEN** a valid workflow run writes artifacts listed in its manifest
- **THEN** the local artifact index contains `ArtifactRef` records for those manifest artifacts

#### Scenario: Manifest index path escapes the run root
- **WHEN** a manifest artifact path resolves outside the canonical run root
- **THEN** indexing fails without reading external bytes or persisting an index reference

### Requirement: Workflow runs populate the event store
The system SHALL persist workflow events into the storage-owned event store only for validated single-segment run identifiers.

#### Scenario: Workflow events are written
- **WHEN** a workflow run with a valid run identifier writes `events.jsonl`
- **THEN** the local event store contains the same workflow event records
- **AND** step events can be queried by step id

#### Scenario: Event run identifier is unsafe
- **WHEN** event persistence receives an unsafe run identifier
- **THEN** it fails before resolving or writing an event-store path
