# source-error-top-level-policy-fields Specification

## Purpose
TBD - created by archiving change source-error-top-level-policy-fields. Update Purpose after archive.
## Requirements
### Requirement: Source errors expose core policy fields
The system SHALL expose core source error policy fields at the top level of
serialized source errors.

#### Scenario: Connector returns a non-retryable error
- **WHEN** a connector returns an error with `metadata.retryable=False`
- **THEN** the serialized source error includes `retryable=False`
- **AND** the serialized source error includes the source name

#### Scenario: Legacy source error omits retryable
- **WHEN** a source error is created without an explicit retryable value
- **THEN** the serialized source error includes a backward-compatible
  `retryable=True` value
