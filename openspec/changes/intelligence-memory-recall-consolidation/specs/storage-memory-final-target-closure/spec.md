## ADDED Requirements

### Requirement: Storage queries intelligence memory objects
The system SHALL allow PostgreSQL-backed intelligence memory repositories to query entities, claims, events, evidence links, decisions, preferences, and event timelines.

#### Scenario: Repository returns topic and entity events
- **WHEN** memory events and event relation rows exist in PostgreSQL
- **THEN** the repository can list events by topic and by entity without graph storage

### Requirement: Storage persists claim history
The system SHALL persist claim status and confidence history records for intelligence memory consolidation.

#### Scenario: Claim history record is appended
- **WHEN** claim consolidation changes status or confidence
- **THEN** the repository appends a memory claim history row containing old state, new state, reason, evidence ID, created time, and metadata

### Requirement: Storage supports simple memory mutations
The system SHALL upsert entities, claims, and events and link events to entities, claims, and evidence through deterministic mutation methods.

#### Scenario: Event links are refreshed
- **WHEN** an event is upserted with entity, claim, and evidence identifiers
- **THEN** event relation rows are refreshed using memory relation tables without requiring foreign keys to legacy claim or evidence tables
