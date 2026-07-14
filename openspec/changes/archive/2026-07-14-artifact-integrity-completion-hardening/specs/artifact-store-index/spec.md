## MODIFIED Requirements

### Requirement: Default local artifact store verifies persisted state
The system SHALL validate local object/metadata pair state, regular-file kind, metadata identity, metadata structure, and SHA-256 before returning artifact content. Before listing an artifact reference, it SHALL validate the metadata record, checksum declaration, identity, URI, and corresponding object file kind, and SHALL reject invalid persisted required fields without string coercion or reading every object solely to recompute its checksum.

#### Scenario: Verified local artifact is read
- **WHEN** object bytes and valid metadata checksum agree
- **THEN** the store returns the original artifact

#### Scenario: Local object or metadata is corrupt
- **WHEN** the pair is partial, metadata is invalid, or checksum comparison fails
- **THEN** the store raises the corresponding shared typed exception and returns no artifact

#### Scenario: Local object target is not a regular file
- **WHEN** the canonical object target exists as a directory or another stable non-regular filesystem node
- **THEN** `LocalArtifactStore.get()` raises `ArtifactStoreMetadataError` before reading content

#### Scenario: Local metadata target is not a regular file
- **WHEN** the canonical metadata target exists as a directory or another stable non-regular filesystem node
- **THEN** `LocalArtifactStore.get()` raises `ArtifactStoreMetadataError` before parsing metadata

#### Scenario: Listed metadata has a null required field
- **WHEN** `LocalArtifactStore.list()` encounters persisted metadata whose `artifact_id` or `uri` is missing, null, blank, or non-string
- **THEN** it raises `ArtifactStoreMetadataError` for corrupt persisted metadata
- **AND** it never constructs or returns an artifact reference containing the literal string `"None"` or another coerced representation

#### Scenario: Listed metadata or object is not a regular file
- **WHEN** `LocalArtifactStore.list()` encounters a matching metadata candidate or its canonical object target as a directory or another stable non-regular filesystem node
- **THEN** it raises `ArtifactStoreMetadataError` before parsing or returning that record
- **AND** it does not expose a raw platform `OSError`

#### Scenario: Listed metadata JSON is corrupt
- **WHEN** `LocalArtifactStore.list()` encounters malformed JSON, a non-object payload, invalid identity, invalid URI, invalid checksum, or invalid metadata shape
- **THEN** it raises `ArtifactStoreMetadataError` and returns no partial listing
