# run-replay-cli Specification

## Purpose
TBD - created by archiving change run-replay-cli. Update Purpose after archive.
## Requirements
### Requirement: Run inspection builds replay bundles
The system SHALL validate the canonical terminal run manifest, capture and verify all manifest-listed artifacts, and preflight every selected artifact-index target before building a strict read-only replay bundle solely from immutable verified snapshots.

#### Scenario: Run artifacts verify
- **WHEN** replay is requested for a run whose canonical manifest is valid and whose non-manifest artifacts match valid expected checksums
- **THEN** the result includes manifest, events, and artifact entries decoded from the verified snapshots

#### Scenario: Canonical run manifest is invalid
- **WHEN** strict replay receives a manifest that fails `validate_run_manifest(..., require_terminal_artifact=True)`
- **THEN** replay raises `ArtifactStoreMetadataError` before decoding or returning artifact content

#### Scenario: Replay artifact fails integrity
- **WHEN** any non-manifest artifact is missing expected integrity metadata, has corrupt metadata, is not a regular file, has mismatched size or content type, or has mismatched bytes
- **THEN** replay fails as a whole without returning any artifact content

#### Scenario: Manifest-listed bytes change after preflight
- **WHEN** a manifest-listed file is replaced after its bytes pass strict preflight
- **THEN** replay uses the captured verified bytes for artifacts, events, step results, and every other projection
- **AND** replay never returns bytes read from that path after preflight

#### Scenario: Index entry uses a top-level checksum
- **WHEN** a selected verified artifact index entry contains a valid top-level `checksum` and its canonical target bytes match it
- **THEN** strict replay captures the target in the verified snapshot set and expands the entry from those bytes

#### Scenario: Index entry uses the nested compatibility checksum
- **WHEN** a selected index entry omits top-level `checksum`, contains a valid `artifact_ref.checksum`, and its canonical target bytes match it
- **THEN** strict replay uses the nested checksum as the compatibility fallback and expands the verified entry

#### Scenario: Index checksum declarations conflict
- **WHEN** a selected index entry contains both top-level `checksum` and `artifact_ref.checksum` with different values
- **THEN** strict replay raises `ArtifactStoreMetadataError` without choosing either checksum or returning replay content

#### Scenario: Index entry has no checksum
- **WHEN** a selected index entry has neither a valid top-level `checksum` nor a valid `artifact_ref.checksum`
- **THEN** strict replay raises `ArtifactStoreMetadataError` before reading or returning the target content

#### Scenario: Index entry metadata is invalid
- **WHEN** a selected index entry has an unsafe or escaping path, a duplicate projected artifact key, an invalid optional serialized `size_bytes` or `content_type`, or a serialized size or content type that disagrees with its canonical target
- **THEN** strict replay raises the corresponding shared typed path or metadata failure
- **AND** no replay projection is returned

#### Scenario: Index top-level content type is a business projection
- **WHEN** a selected `source_response_headers` entry uses top-level `content_type` for the source HTTP response and `artifact_ref.content_type` for the persisted JSON artifact
- **THEN** strict replay validates the file against `artifact_ref.content_type`
- **AND** it preserves the top-level business field without treating it as conflicting file integrity metadata

#### Scenario: Index target checksum mismatches
- **WHEN** a selected index target's bytes do not match the resolved valid entry checksum
- **THEN** strict replay raises `ArtifactChecksumMismatchError`
- **AND** no replay projection is returned

#### Scenario: One selected index entry fails preflight
- **WHEN** one of multiple selected index entries is missing, non-regular, unsafe, malformed, or fails integrity verification
- **THEN** the entire strict replay fails before any manifest-listed or index-expanded content is decoded or returned

### Requirement: Replay output redacts sensitive fields
The system SHALL redact sensitive keys from replay events and JSON artifacts.

#### Scenario: Artifact contains an API key field
- **WHEN** replay is generated
- **THEN** the sensitive value is replaced with a redacted marker

### Requirement: CLI exposes run replay
The system SHALL expose strict run replay through the CLI and SHALL return exit code `1` for typed path, checksum, metadata, or store-configuration failures.

#### Scenario: Run replay is requested
- **WHEN** `news runs replay <run_id> --json` is run for a verified run
- **THEN** the command prints a machine-readable replay bundle

#### Scenario: Run replay integrity fails
- **WHEN** strict replay encounters a typed integrity failure
- **THEN** the command prints a sanitized error to stderr, returns exit code `1`, and prints no replay artifact content
