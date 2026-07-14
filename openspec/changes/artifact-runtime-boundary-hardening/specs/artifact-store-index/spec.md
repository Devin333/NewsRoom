## MODIFIED Requirements

### Requirement: Artifact references are serializable
The system SHALL provide a serializable storage-owned artifact reference model that preserves valid fields and rejects missing, null, blank, non-string, or conflicting required aliases during deserialization.

#### Scenario: ArtifactRef is converted to dict and back
- **WHEN** a valid artifact reference is serialized and deserialized
- **THEN** artifact id, run id, step id, path, checksum, redaction flag, and metadata are preserved

#### Scenario: ArtifactRef path aliases are invalid
- **WHEN** serialized input omits both `path` and `uri`, supplies a blank value, or supplies conflicting aliases
- **THEN** deserialization raises `ValueError` without constructing an invalid reference

### Requirement: Filesystem artifact store persists artifact bytes
The system SHALL persist artifact bytes only to canonical filesystem descendants of the configured run root and return canonical artifact references.

#### Scenario: Artifact is written and read
- **WHEN** the filesystem artifact store writes an artifact with valid identifiers and a valid relative path
- **THEN** the artifact file exists under the run directory
- **AND** reading by `ArtifactRef` returns the original bytes

#### Scenario: Unsafe store path is rejected
- **WHEN** a store operation receives an unsafe run identifier or relative artifact path
- **THEN** the operation raises `ArtifactPathError` before reading, writing, deleting, or listing content outside the configured root

### Requirement: Local artifact index lists artifacts by run and step
The system SHALL persist valid artifact references to a local JSON index and reject unsafe identifiers before resolving index paths.

#### Scenario: Multiple artifacts are indexed
- **WHEN** artifacts for a valid run and step are indexed
- **THEN** `list_by_run` returns all run artifacts
- **AND** `list_by_step` returns only artifacts for the requested step

#### Scenario: Unsafe index identifier is rejected
- **WHEN** an index operation receives an unsafe run, step, or artifact identifier
- **THEN** it fails before creating or reading an index record outside the configured index root
