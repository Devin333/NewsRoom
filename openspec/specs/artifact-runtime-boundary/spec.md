# artifact-runtime-boundary Specification

## Purpose
TBD - created by archiving change artifact-runtime-boundary-hardening. Update Purpose after archive.
## Requirements
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

### Requirement: Graph artifact governance remains artifact-owned during Workflow retirement

The system SHALL preserve the existing Graph artifact catalog, quota, usage-ledger, GC, cost-report, alert, context-loading, and lifecycle contracts under the artifact owner while retiring Workflow runtime dependencies. Every live Graph artifact manager, publisher, inspector, and physical lifecycle adapter SHALL use an artifact-owned Graph terminal-manifest and manifest-hash contract and SHALL NOT import or invoke `framework.workflow.runtime.manifest`, a Workflow inspector, or a legacy Workflow writer.

#### Scenario: Existing Graph artifact governance is migrated

- **WHEN** the Graph-only cutover migrates artifact manifest and inspection callers
- **THEN** catalog deduplication, quota accounting, sanitized usage facts, controlled GC, cost reports, alerts, context loading, and physical lifecycle behavior remain available through `framework.harness.artifacts` contracts
- **AND** no forwarding compatibility facade to the Workflow runtime is introduced

#### Scenario: Graph physical lifecycle updates manifest membership

- **WHEN** an authorized GC operation detaches, quarantines, or purges a Graph artifact
- **THEN** the lifecycle adapter verifies and updates membership through the artifact-owned Graph terminal-manifest/hash contract
- **AND** source scans find no live dependency from the lifecycle, manager, publisher, inspection, or composition path to `framework.workflow.runtime.manifest`

#### Scenario: Legacy manifest needs historical conversion

- **WHEN** an unmigrated Workflow manifest must be retained for audit or conversion
- **THEN** only the bounded offline migrator may read its exact schema and checksum
- **AND** the Graph artifact governance runtime, production composition, and operator surface do not import that migration reader

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
