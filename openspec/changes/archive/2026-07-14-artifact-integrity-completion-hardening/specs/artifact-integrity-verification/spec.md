## MODIFIED Requirements

### Requirement: Local artifact pair states are deterministic
The system SHALL distinguish absent, partial, corrupt, non-regular, legacy-unverified, and verified local artifact states before constructing an artifact.

#### Scenario: Both object and metadata are absent
- **WHEN** a requested artifact has neither persisted object nor metadata
- **THEN** the store returns `None`

#### Scenario: Only metadata exists
- **WHEN** committed metadata exists but its object is missing
- **THEN** the store raises `ArtifactNotFoundError`

#### Scenario: Only object exists
- **WHEN** an object exists without its metadata commit marker
- **THEN** the store raises `ArtifactStoreMetadataError`

#### Scenario: Object or metadata target is not a regular file
- **WHEN** either canonical local-store target exists as a directory or another stable non-regular filesystem node
- **THEN** the store raises `ArtifactStoreMetadataError` before attempting JSON or byte decoding
- **AND** no raw platform `OSError` is exposed for that persisted-state classification

#### Scenario: Legacy metadata lacks checksum
- **WHEN** otherwise valid legacy local-store metadata has no checksum
- **THEN** the store returns content marked with `_artifact_integrity="checksum_missing"`
- **AND** integrity inspection does not report the artifact as valid

### Requirement: Service-facing workflow reads are strict
The system SHALL validate path, metadata, file kind, size, and SHA-256 for every non-manifest artifact before returning direct artifact or replay content, and strict replay SHALL decode every projection only from the exact immutable byte snapshots that passed preflight.

#### Scenario: Direct artifact bytes are tampered
- **WHEN** a manifest-listed artifact no longer matches its expected checksum
- **THEN** the strict read raises `ArtifactChecksumMismatchError` before decoding, redaction, or content return

#### Scenario: Strict replay contains a corrupt artifact
- **WHEN** any non-manifest replay artifact has missing or invalid checksum metadata or mismatched bytes
- **THEN** replay fails as a whole without returning any artifact content

#### Scenario: Manifest uses self-checksum sentinel
- **WHEN** the `manifest` artifact metadata checksum is `"pending"` and all other artifacts verify
- **THEN** strict replay accepts the manifest self-checksum exception and succeeds

#### Scenario: A verified file changes after snapshot capture
- **WHEN** a manifest-listed artifact is replaced after strict preflight captures and verifies its bytes but before replay projections are constructed
- **THEN** artifact records, events, step results, and other projections use only the captured verified bytes
- **AND** strict replay does not reopen the path or return any replacement bytes

#### Scenario: Strict replay preflight fails before decoding
- **WHEN** any required manifest-listed or selected index-referenced artifact fails strict preflight
- **THEN** replay returns no partial artifact, event, step-result, index-expanded, decoded, redacted, or truncated projection
