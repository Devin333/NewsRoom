# artifact-runtime-boundary Specification

## Purpose
TBD - created by archiving change artifact-runtime-boundary-hardening. Update Purpose after archive.
## Requirements
### Requirement: Artifact filesystem access uses one path boundary
The system SHALL validate every artifact-root identity and relative path through the shared artifact path boundary before filesystem access or durable side effects.

#### Scenario: Unsafe run identifier is rejected
- **WHEN** a caller supplies a traversal, absolute, drive-relative, UNC, device, reserved-character, trailing-dot/space, ADS, or DOS-device run identifier
- **THEN** the system rejects it with `ArtifactPathError` or the documented adapter failure before creating a directory, file, event, manifest, checkpoint, or index record

#### Scenario: Nested artifact path stays inside the run root
- **WHEN** a caller supplies a valid nested relative path such as `steps/s1/output.json`
- **THEN** the canonical target is resolved below the canonical run root and access succeeds

#### Scenario: Linked target escapes the root
- **WHEN** a path below the artifact root traverses a symlink or junction to an external target
- **THEN** canonical descendant resolution rejects the target before external content is read or written

### Requirement: Infrastructure owns trusted artifact metadata
The system SHALL reject caller metadata that conflicts with publisher- or artifact-step-owned identity, location, integrity, lifecycle, content-description, or redaction fields.

#### Scenario: Publisher identity conflict has no side effect
- **WHEN** caller metadata includes `publisher_id` or `run_id`
- **THEN** publication fails without writing a file or returning an artifact reference

#### Scenario: Artifact step reserved metadata fails deterministically
- **WHEN** nested `artifact_metadata` includes any reserved artifact-step key
- **THEN** the step fails without writing an artifact reference to the buffer, manifest, index, or filesystem

#### Scenario: Custom metadata remains supported
- **WHEN** caller metadata contains only non-reserved custom keys
- **THEN** publication preserves the metadata and applies existing recursive sensitive-value redaction

### Requirement: Serialized artifact references reject missing identity
The system SHALL reject missing, null, blank, non-string, or ambiguous required reference fields before producing an artifact reference object.

#### Scenario: Missing URI alias is rejected
- **WHEN** `ArtifactReference.from_dict()` or `ArtifactRef.from_dict()` receives neither a valid `uri` nor a valid legacy `path`
- **THEN** deserialization raises `ValueError` and never produces the string `"None"`

#### Scenario: Conflicting aliases are rejected
- **WHEN** both `uri` and `path` are present with different strings
- **THEN** deserialization rejects the ambiguous reference

#### Scenario: Remote general reference remains valid
- **WHEN** a general `ArtifactReference` uses a URI such as `s3://bucket/key`
- **THEN** model and general validation accept it while local filesystem adapters remain responsible for rejecting unsupported local access
