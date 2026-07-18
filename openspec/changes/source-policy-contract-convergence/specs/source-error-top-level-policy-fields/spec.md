## MODIFIED Requirements

### Requirement: Source errors expose core policy fields
The system SHALL expose core Source error policy fields at the top level of
serialized Source errors. The single interface-boundary SourceError mapper SHALL
preserve every field and SHALL NOT recalculate retryability or occurrence time.

#### Scenario: Connector returns a non-retryable error
- **WHEN** a connector returns an error with `metadata.retryable=False`
- **THEN** the serialized Source error includes `retryable=False`
- **AND** the serialized Source error includes the source name

#### Scenario: Legacy source error omits retryable
- **WHEN** a Source error is created without an explicit retryable value
- **THEN** the serialized Source error includes a backward-compatible
  `retryable=True` value

#### Scenario: SourceError mapper round trip is lossless
- **GIVEN** an infrastructure SourceError contains every public field, nested
  metadata, and an aware non-UTC `occurred_at`
- **WHEN** the error crosses the explicit Source mapper and is serialized
- **THEN** source identity, error type, message, URL, retryability, refs, metadata,
  occurrence instant, and timezone awareness are preserved
- **AND** object-to-object mapping preserves the original timezone offset

#### Scenario: Mapper does not replace occurrence time
- **WHEN** an old SourceError is mapped after its original occurrence
- **THEN** the mapped `occurred_at` equals the original value
- **AND** mapper execution time is not emitted

#### Scenario: Serialized legacy types are normalized
- **WHEN** a serialized SourceError contains an ISO 8601 `occurred_at` and a
  case-insensitive `true`, `false`, `1`, `0`, `yes`, `no`, `on`, or `off` string
  for `retryable`
- **THEN** the reader produces an aware `datetime` and a boolean
- **AND** re-serialization succeeds without replacing the occurrence instant

#### Scenario: Unknown boolean string is rejected
- **WHEN** serialized `retryable` contains any other non-boolean value
- **THEN** the SourceError reader raises a deterministic validation error

#### Scenario: Retryable precedence is deterministic
- **WHEN** top-level `retryable` is present
- **THEN** its normalized boolean value overrides legacy metadata
- **WHEN** top-level `retryable` is absent
- **THEN** legacy metadata is used, or `True` is used when both are absent
