# workflow-storage-indexing Specification

## Purpose
TBD - created by archiving change workflow-storage-indexing. Update Purpose after archive.
## Requirements
### Requirement: Workflow runs populate the artifact index
The system SHALL index artifacts produced by local workflow runs.

#### Scenario: Workflow run completes
- **WHEN** a workflow run writes artifacts listed in its manifest
- **THEN** the local artifact index contains `ArtifactRef` records for those manifest artifacts

### Requirement: Workflow runs populate the event store
The system SHALL persist workflow events into the storage-owned event store.

#### Scenario: Workflow events are written
- **WHEN** a workflow run writes `events.jsonl`
- **THEN** the local event store contains the same workflow event records
- **AND** step events can be queried by step id
