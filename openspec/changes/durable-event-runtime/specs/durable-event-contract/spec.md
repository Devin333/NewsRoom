## ADDED Requirements

### Requirement: Canonical stored event has one authoritative context
The system SHALL persist every durable event as one canonical stored envelope containing stable event identity, event and data schema identity, producer source, optional subject, occurrence and observation times, stream identity and sequence, business context, correlation and causation, optional trace context, security scope, payload or payload reference, extensions, a producer-content checksum, and a complete-record checksum.

#### Scenario: Typed workflow event reaches the durable boundary
- **WHEN** a typed workflow or Harness event is published
- **THEN** the runtime converts it to the canonical stored envelope before persistence
- **AND** the stored envelope contains exactly one authoritative value for each run, workflow, step, trace, producer, and schema field

#### Scenario: Legacy duplicated context conflicts
- **WHEN** a legacy event and envelope provide different non-empty values for the same authoritative field
- **THEN** the runtime rejects or quarantines the record with a typed conflict reason
- **AND** it does not silently prefer either value

### Requirement: Event contents are deeply immutable and canonical
The system SHALL create a canonical JSON snapshot before accepting an event and SHALL prevent caller or consumer mutations from changing the accepted event contents, producer-content checksum, or complete-record checksum.

#### Scenario: Caller mutates nested input after construction
- **WHEN** a caller changes a nested dictionary or list used to construct an accepted event
- **THEN** the accepted event payload, serialized form, and both checksums remain unchanged

#### Scenario: Payload contains an unsupported runtime object
- **WHEN** a payload contains a value outside the registered canonical JSON contract
- **THEN** publication fails before sequence allocation, storage, delivery, or external side effects

### Requirement: Event identity is stable and collision safe
The system SHALL assign or accept a stable `event_id` before the first append, SHALL calculate `content_checksum` over the complete canonical pre-storage acceptance projection after security projection but before store-assigned fields, and SHALL treat an identical duplicate append as idempotent while rejecting reuse of that identity for different content.

#### Scenario: Identical event is appended twice
- **WHEN** the same `event_id` and `content_checksum` are appended more than once
- **THEN** the store returns the already accepted event and original stream sequence
- **AND** it does not create another event or delivery row

#### Scenario: Event id is reused for different content
- **WHEN** an existing `event_id` is submitted with a different `content_checksum`
- **THEN** the runtime raises a typed identity-collision error
- **AND** neither record is silently overwritten

#### Scenario: Event id is reused across a security or stream boundary
- **WHEN** an existing `event_id` is submitted with the same payload but a different stream, tenant, schema, classification, business context, producer, or payload reference
- **THEN** the changed pre-storage acceptance projection produces a different `content_checksum`
- **AND** the runtime rejects the append as an identity collision rather than returning the existing event

### Requirement: Envelope and data schemas are versioned independently
The system SHALL version the shared envelope with `envelope_schema` and the domain payload with `data_schema`, and SHALL validate the `(event_type, data_schema)` pair through a deterministic schema catalog before append.

#### Scenario: Registered event satisfies its payload schema
- **WHEN** a publisher submits a supported event type and schema with a valid payload
- **THEN** the schema catalog validates it and publication may continue

#### Scenario: Payload violates a registered schema
- **WHEN** a publisher submits a payload that violates the registered schema
- **THEN** publication fails before sequence allocation, durable append, or delivery
- **AND** the failure identifies the event type, schema, and validation path without exposing a secret value

### Requirement: Schema evolution is explicit and deterministic
The system SHALL support ordered pure upcasters between registered historical data schemas and SHALL quarantine unsupported, ambiguous, or invalid historical records rather than guessing missing facts.

#### Scenario: Historical v1 record has a complete upcast chain
- **WHEN** a v1 historical event is read by a consumer requiring v3 and registered `v1 -> v2 -> v3` upcasters exist
- **THEN** the runtime applies the same ordered pure transformation on every read
- **AND** preserves the original event identity and stored bytes

#### Scenario: Historical record has an unknown schema
- **WHEN** an importer or reader encounters an unregistered schema or a missing upcast step
- **THEN** the record enters quarantine with a typed reason
- **AND** normal consumers do not receive it

#### Scenario: Historical occurrence time is missing
- **WHEN** a legacy record has no valid occurrence timestamp
- **THEN** the importer quarantines it or records an explicit unresolved-time status
- **AND** it does not substitute the import time as the occurrence time

### Requirement: Event time and observation time have distinct semantics
The system SHALL preserve `occurred_at` as the time the fact happened and SHALL assign `observed_at` as the time the durable store accepted it, with both values normalized to UTC.

#### Scenario: Delayed event is ingested
- **WHEN** an event occurred before it reached the runtime
- **THEN** its `occurred_at` remains the original occurrence time
- **AND** its later `observed_at` is independently recorded

#### Scenario: Events have equal occurrence timestamps
- **WHEN** two events in one stream have the same `occurred_at`
- **THEN** their authoritative order is determined by `stream_sequence`, not by timestamp or event id

### Requirement: Content and record checksums have distinct coverage
The system SHALL compute `content_checksum` from the canonical encoding of `envelope_schema`, `event_id`, `event_type`, `data_schema`, `source`, `subject`, `occurred_at`, `stream_id`, correlation and causation, business context, producer, trace context, tenant and classification, content type, the post-security payload or payload reference with expected checksum, and extensions. It SHALL exclude only store-assigned `observed_at` and `stream_sequence`, both checksum fields themselves, and delivery, checkpoint, lease, replay, and operator state. The system SHALL compute `record_checksum` after assigning `observed_at` and `stream_sequence` to protect the complete immutable stored record except `record_checksum` itself.

#### Scenario: Uncertain commit is retried
- **WHEN** a publisher retries the same event id and producer content after losing the commit response
- **THEN** the stable `content_checksum` matches the previously committed event
- **AND** the store returns that event's original observation time, sequence, and record checksum

#### Scenario: Stored sequence is tampered with
- **WHEN** a stored event's sequence or observation time changes without recomputing the record
- **THEN** `record_checksum` verification fails before query or replay applies the event

### Requirement: Business causation and trace parentage are separate
The system SHALL represent event-to-event causation with `causation_id` and distributed tracing relationships with trace/span context or links, and SHALL NOT use either as a substitute for the other.

#### Scenario: Tool result is caused by a tool request
- **WHEN** a tool-result event follows a tool-request event
- **THEN** the result records the request event id as `causation_id`
- **AND** trace parentage is recorded independently according to the active span

### Requirement: Inline payload and extension limits are enforced
The system SHALL enforce configurable nonzero limits for inline payload size, extension count, extension size, and attribute types. It SHALL allow an integrity-protected artifact reference for oversized non-sensitive content only when schema policy permits it, and SHALL require a separately authorized secure payload reference for reference-only, confidential, or restricted content.

#### Scenario: Inline payload exceeds the configured limit
- **WHEN** canonical serialization exceeds the configured inline payload limit
- **THEN** publication fails with a typed payload-too-large error unless a valid `payload_ref` is supplied

#### Scenario: Event uses a payload reference
- **WHEN** oversized non-sensitive content is represented by a schema-permitted `payload_ref`
- **THEN** the stored event includes the reference, content type, and expected checksum
- **AND** does not duplicate the referenced content inline

#### Scenario: Protected content has no secure payload store
- **WHEN** a reference-only, confidential, or restricted value is supplied and no payload store proves tenant-scoped authorization, encryption in transit and at rest, integrity verification, and audited access
- **THEN** publication fails before sequence allocation, persistence, projection, or delivery
- **AND** an ordinary `ArtifactReference`, local path, or checksum-only reference is not accepted as secure storage

### Requirement: Security projection precedes every durable write and export
The system SHALL apply one schema-aware security projection before local or PostgreSQL persistence and before JSONL, log, dead-letter, metric, trace, or operator export.

#### Scenario: Event contains a forbidden secret field
- **WHEN** a payload contains a field classified as forbidden or reference-only
- **THEN** publication rejects it or replaces it only with a reference from a validated secure payload store according to schema policy
- **AND** the raw value is absent from every durable event and diagnostic output

#### Scenario: Backend implementations receive the same event
- **WHEN** the same valid event is written to local and PostgreSQL adapters
- **THEN** both receive the same post-projection canonical payload and checksum
- **AND** neither backend performs a weaker security policy

### Requirement: Tenant and classification scope are infrastructure-owned
The system SHALL record `tenant_id` when applicable and one of `public`, `internal`, `confidential`, or `restricted` as `security_classification`, and SHALL prevent extensions or payload fields from overriding those values.

#### Scenario: Caller attempts to forge tenant scope
- **WHEN** a caller supplies a conflicting tenant or classification in extensions or metadata
- **THEN** publication fails before persistence

#### Scenario: Tenant-scoped history is queried or exported
- **WHEN** an authorized application service reads, exports, replays, or operates on a tenant-scoped stream
- **THEN** the tenant scope is preserved through the entire operation
- **AND** event or trace identifiers alone do not grant access

### Requirement: Legacy event formats have a bounded migration contract
The system SHALL provide explicit readers for supported legacy framework, storage, and workflow JSONL records for one migration release and SHALL produce a deterministic migration report without rewriting the source history.

#### Scenario: Valid legacy JSONL is imported
- **WHEN** a supported legacy record has complete and non-conflicting fields
- **THEN** the importer maps it to one canonical event with a stable mapping record
- **AND** maps the 0-based line offset separately from the 1-based stream sequence

#### Scenario: Legacy record cannot be migrated safely
- **WHEN** a legacy record has conflicting identity, duplicate content, invalid time, or unsupported schema
- **THEN** the migration report records a quarantine entry and source location
- **AND** the importer continues or fails according to an explicit fail-fast option without inventing values
