## ADDED Requirements

### Requirement: Artifact integrity outcomes emit stable structured events
The system SHALL emit exactly one structured log record at the deterministic owner of each classified artifact boundary or integrity outcome, using the stable event name and flat dimensions defined by this capability.

#### Scenario: Artifact path is rejected
- **WHEN** the shared artifact path boundary rejects an identity, relative path, canonical descendant, symlink, or junction target
- **THEN** the owner emits `artifact_path_rejected_total` at warning level
- **AND** the record contains only normalized `field` and `operation` dimensions

#### Scenario: Reserved artifact metadata is rejected
- **WHEN** a publisher or artifact step rejects a caller-provided reserved metadata key
- **THEN** the owner emits `artifact_reserved_metadata_rejected_total` at warning level
- **AND** the record contains only normalized `key` and `publisher` dimensions

#### Scenario: Artifact checksum mismatches
- **WHEN** shared checksum verification computes bytes that do not match a valid expected checksum
- **THEN** the owner emits `artifact_checksum_mismatch_total` at warning level
- **AND** the record contains only normalized `store` and `operation` dimensions

#### Scenario: Persisted artifact metadata is corrupt
- **WHEN** an artifact store or strict workflow reader classifies persisted state as `ArtifactStoreMetadataError`
- **THEN** the deterministic boundary that catches the typed failure emits `artifact_metadata_corrupt_total` at warning level
- **AND** the record contains only a normalized `store` dimension

#### Scenario: Expected artifact checksum is missing
- **WHEN** a legacy-compatible local-store read or a strict reader detects that required checksum metadata is absent
- **THEN** the owner emits `artifact_checksum_missing_total` at warning level
- **AND** the record contains only a normalized `store` dimension

#### Scenario: Integrity inspection finishes
- **WHEN** generic artifact integrity inspection completes or cannot run because required verification configuration is unavailable
- **THEN** the owner emits `artifact_integrity_inspection_total` with a normalized `result` dimension
- **AND** a successful inspection outcome uses info level
- **AND** an invalid or configuration-failure outcome uses warning level

### Requirement: Artifact observability payloads are safe and bounded
The system SHALL build artifact integrity event payloads from an explicit allow-list of fixed event names, normalized dimension labels, and severity, and SHALL NOT serialize artifact content, raw filesystem paths, raw metadata values, credentials, secrets, tokens, exception text, or tracebacks.

#### Scenario: Rejected input contains sensitive material
- **WHEN** an unsafe path, metadata value, artifact body, or exception contains a secret-like value
- **THEN** the structured event contains the applicable stable event name and allow-listed labels
- **AND** the event message and dimensions contain none of the sensitive value, raw input, raw path, artifact content, exception text, or traceback

#### Scenario: A dimension value is not in its allow-list
- **WHEN** instrumentation receives an unknown value for `field`, `operation`, `key`, `publisher`, `store`, or `result`
- **THEN** the helper emits a fixed safe fallback label rather than the raw value
