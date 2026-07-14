# artifact-store-index Specification

## Purpose
TBD - created by archiving change artifact-store-index. Update Purpose after archive.
## Requirements
### Requirement: Artifact references are serializable
The system SHALL provide a serializable storage-owned artifact reference model.

#### Scenario: ArtifactRef is converted to dict and back
- **WHEN** an artifact reference is serialized and deserialized
- **THEN** artifact id, run id, step id, path, checksum, redaction flag, and metadata are preserved

### Requirement: Filesystem artifact store persists artifact bytes
The system SHALL persist artifact bytes to real filesystem paths and return canonical artifact references.

#### Scenario: Artifact is written and read
- **WHEN** the filesystem artifact store writes an artifact
- **THEN** the artifact file exists under the run directory
- **AND** reading by `ArtifactRef` returns the original bytes

### Requirement: Local artifact index lists artifacts by run and step
The system SHALL persist artifact references to a local JSON index.

#### Scenario: Multiple artifacts are indexed
- **WHEN** artifacts for a run and step are indexed
- **THEN** `list_by_run` returns all run artifacts
- **AND** `list_by_step` returns only artifacts for the requested step
