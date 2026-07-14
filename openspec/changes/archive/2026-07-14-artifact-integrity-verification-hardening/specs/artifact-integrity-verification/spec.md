## ADDED Requirements

### Requirement: Local artifact integrity uses shared typed failures
The system SHALL expose one public exception contract for missing artifacts, checksum mismatch, corrupt store metadata, and integrity verification requested without a store.

#### Scenario: Persisted checksum does not match bytes
- **WHEN** a local artifact read computes a SHA-256 different from the valid persisted checksum
- **THEN** the read raises `ArtifactChecksumMismatchError` before returning artifact content

#### Scenario: Persisted metadata is corrupt
- **WHEN** local artifact metadata is malformed, structurally invalid, or contains an invalid checksum format
- **THEN** the read raises `ArtifactStoreMetadataError`

### Requirement: Local artifact publication uses metadata-last replacement
The system SHALL write local artifact objects and metadata through unique temporary files and SHALL replace metadata last as the commit marker.

#### Scenario: Local artifact write succeeds
- **WHEN** object and metadata temporary writes and replacements complete
- **THEN** a subsequent read returns the original bytes with a verified SHA-256 checksum

#### Scenario: Local artifact write is interrupted
- **WHEN** a temporary write or replacement fails before metadata commit
- **THEN** the operation raises the underlying failure, removes its temporary files, and does not expose a newly verified half-written artifact

### Requirement: Local artifact pair states are deterministic
The system SHALL distinguish absent, partial, corrupt, legacy-unverified, and verified local artifact states before constructing an artifact.

#### Scenario: Both object and metadata are absent
- **WHEN** a requested artifact has neither persisted object nor metadata
- **THEN** the store returns `None`

#### Scenario: Only metadata exists
- **WHEN** committed metadata exists but its object is missing
- **THEN** the store raises `ArtifactNotFoundError`

#### Scenario: Only object exists
- **WHEN** an object exists without its metadata commit marker
- **THEN** the store raises `ArtifactStoreMetadataError`

#### Scenario: Legacy metadata lacks checksum
- **WHEN** otherwise valid legacy local-store metadata has no checksum
- **THEN** the store returns content marked with `_artifact_integrity="checksum_missing"`
- **AND** integrity inspection does not report the artifact as valid

### Requirement: Integrity inspection reports only performed checks
The system SHALL report successful integrity only for artifacts that were actually read and verified and SHALL count each classified verification attempt exactly once.

#### Scenario: Empty manifest has no store
- **WHEN** integrity inspection receives an empty manifest and no store
- **THEN** it returns `valid=True` and `checked_count=0`

#### Scenario: Non-empty manifest has no store
- **WHEN** integrity inspection receives one or more references and no store
- **THEN** it raises `ArtifactStoreRequiredError`

#### Scenario: Manifest has mixed integrity failures
- **WHEN** references resolve to missing, mismatched, corrupt-metadata, checksum-missing, and valid artifacts
- **THEN** the report contains a stable issue for every classified result
- **AND** `checked_count` equals the number of attempted store reads
- **AND** `valid` is false

### Requirement: Service-facing workflow reads are strict
The system SHALL validate path, metadata, and SHA-256 for every non-manifest artifact before returning direct artifact or replay content.

#### Scenario: Direct artifact bytes are tampered
- **WHEN** a manifest-listed artifact no longer matches its expected checksum
- **THEN** the strict read raises `ArtifactChecksumMismatchError` before decoding, redaction, or content return

#### Scenario: Strict replay contains a corrupt artifact
- **WHEN** any non-manifest replay artifact has missing or invalid checksum metadata or mismatched bytes
- **THEN** replay fails as a whole without returning any artifact content

#### Scenario: Manifest uses self-checksum sentinel
- **WHEN** the `manifest` artifact metadata checksum is `"pending"` and all other artifacts verify
- **THEN** strict replay accepts the manifest self-checksum exception and succeeds
