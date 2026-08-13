## MODIFIED Requirements

### Requirement: Artifact filesystem access uses one path boundary

The system SHALL validate every artifact-root identity and relative path, including Graph run manifests and migration-only legacy reference metadata, through the shared artifact path boundary before filesystem access or durable side effects. Migration-only legacy metadata SHALL never be accepted by a live Graph writer or executor.

#### Scenario: Unsafe run identifier is rejected

- **WHEN** a caller supplies a traversal, absolute, drive-relative, UNC, device, reserved-character, trailing-dot/space, ADS, or DOS-device run identifier
- **THEN** the system rejects it with `ArtifactPathError` or the documented adapter failure before creating a directory, file, event, manifest, checkpoint, or index record

#### Scenario: Nested artifact path stays inside the run root

- **WHEN** a caller supplies a valid nested relative path such as `nodes/n1/output.json`
- **THEN** the canonical target is resolved below the canonical run root and access succeeds

#### Scenario: Linked target escapes the root

- **WHEN** a path below the artifact root traverses a symlink or junction to an external target
- **THEN** canonical descendant resolution rejects the target before external content is read or written

#### Scenario: Artifact detail needs a fallback run directory

- **WHEN** an inspected Graph run has no populated `artifact_dir` and artifact detail must derive the run directory from `artifact_root` and `run_id`
- **THEN** the service validates the run identifier and uses canonical descendant resolution
- **AND** it does not resolve the fallback by directly joining `artifact_root / run_id`

#### Scenario: Migration reference run id is not a string

- **WHEN** the offline migrator receives legacy artifact metadata whose non-null `run_id` raw type is not `str`
- **THEN** migration raises `ArtifactPathError` before string coercion or filesystem access
- **AND** live Graph artifact services never accept that legacy reference type
