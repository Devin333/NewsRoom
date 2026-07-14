## MODIFIED Requirements

### Requirement: Workflow runs populate the event store
The system SHALL accept workflow events only for validated single-segment run identifiers, SHALL append accepted events to the storage-owned durable event store during execution before subscriber visibility, and SHALL generate the run `events.jsonl` artifact as a redacted ordered projection of that durable stream rather than using the file as a post-run indexing source.

#### Scenario: Workflow event is emitted during execution
- **WHEN** a workflow or Harness transition publishes a valid event
- **THEN** the configured storage event store contains the event before asynchronous delivery begins
- **AND** the event has a stable event id and store-assigned stream sequence

#### Scenario: Workflow process stops before finalization
- **WHEN** the process exits after an event append but before run finalization
- **THEN** the committed event remains queryable and available for recovery
- **AND** recovery does not depend on a completed `events.jsonl` file

#### Scenario: Workflow event projection is finalized
- **WHEN** a workflow run finalizes or explicitly refreshes its event projection
- **THEN** `events.jsonl` contains the redacted events from the durable run stream in sequence order
- **AND** the manifest records the projection high watermark and checksum

#### Scenario: Post-run indexing is disabled
- **WHEN** the durable event write path is active
- **THEN** WorkflowRunner does not reread `events.jsonl` to append the same events again
- **AND** storage selection uses the storage-owned event-store factory

#### Scenario: Step events are queried
- **WHEN** the application event reader lists a run by step id or event type
- **THEN** it queries the durable event store with stable sequence pagination
- **AND** API, CLI, MCP, and SSE preserve their compatible response surfaces through application services

#### Scenario: Event store is unavailable to online inspection
- **WHEN** the durable store cannot serve a current event query
- **THEN** the application service returns an explicit unavailable or stale-projection status
- **AND** does not silently present `events.jsonl` as authoritative current state

#### Scenario: Event run identifier is unsafe
- **WHEN** event persistence receives a run identifier that is not one validated path-safe segment, including traversal, absolute, drive-relative, UNC, device, alternate-data-stream, or reserved-device input
- **THEN** it fails before using the value to derive a stream identifier or resolving or writing an event-store or projection path
- **AND** it creates no event, delivery row, manifest update, or `events.jsonl` file
