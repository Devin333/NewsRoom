## MODIFIED Requirements

### Requirement: Artifact inspection reads manifest-listed artifacts
The system SHALL list only canonical manifest-listed artifact paths and SHALL return direct artifact content only after the canonical terminal run manifest and strict expected-checksum contract validate successfully.

#### Scenario: Artifact list is requested
- **WHEN** a valid run manifest contains valid artifact entries
- **THEN** the service returns artifact summaries with key, relative path, content type, and size

#### Scenario: Inspection path is unsafe
- **WHEN** a run identifier or manifest artifact path is traversal, absolute, drive-relative, UNC/device, linked outside the root, or otherwise invalid
- **THEN** inspection fails before reading content outside the configured artifact root

#### Scenario: Artifact content is tampered
- **WHEN** direct artifact detail is requested and persisted bytes do not match valid expected metadata
- **THEN** inspection raises `ArtifactChecksumMismatchError` and returns no content

#### Scenario: Artifact detail manifest is structurally invalid
- **WHEN** direct artifact detail receives a manifest that fails `validate_run_manifest(..., require_terminal_artifact=True)`
- **THEN** inspection wraps the canonical `RunManifestError` as `ArtifactStoreMetadataError`
- **AND** it does not resolve, decode, redact, or return the requested artifact content
