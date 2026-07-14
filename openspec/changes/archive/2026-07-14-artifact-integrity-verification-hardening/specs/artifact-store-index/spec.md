## MODIFIED Requirements

### Requirement: Filesystem artifact store persists artifact bytes
The system SHALL persist artifact bytes only to canonical filesystem descendants, SHALL return canonical artifact references, and SHALL verify a supplied checksum before returning persisted bytes.

#### Scenario: Artifact is written and read
- **WHEN** the filesystem artifact store writes an artifact with valid identifiers and a valid relative path
- **THEN** the artifact file exists under the run directory
- **AND** reading by `ArtifactRef` returns the original bytes

#### Scenario: Unsafe store path is rejected
- **WHEN** a store operation receives an unsafe run identifier or relative artifact path
- **THEN** the operation raises `ArtifactPathError` before reading, writing, deleting, or listing content outside the configured root

#### Scenario: Filesystem artifact is tampered
- **WHEN** persisted bytes do not match the checksum in `ArtifactRef`
- **THEN** the store raises the shared `ArtifactChecksumMismatchError`

## ADDED Requirements

### Requirement: Default local artifact store verifies persisted state
The system SHALL validate local object/metadata pair state, metadata identity, metadata structure, and SHA-256 before returning an artifact.

#### Scenario: Verified local artifact is read
- **WHEN** object bytes and valid metadata checksum agree
- **THEN** the store returns the original artifact

#### Scenario: Local object or metadata is corrupt
- **WHEN** the pair is partial, metadata is invalid, or checksum comparison fails
- **THEN** the store raises the corresponding shared typed exception and returns no artifact
