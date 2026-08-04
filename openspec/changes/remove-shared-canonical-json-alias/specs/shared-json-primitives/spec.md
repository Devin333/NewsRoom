## ADDED Requirements

### Requirement: Unique Shared stable JSON serializer
The Shared framework SHALL expose `stable_json_dumps` as its single stable JSON string serialization entry point and SHALL NOT expose a second naming-only `canonical_json` wrapper.

#### Scenario: Serialize equivalent mappings
- **WHEN** callers serialize mappings with the same values in different insertion orders
- **THEN** `stable_json_dumps` returns the same compact, key-sorted JSON string

#### Scenario: Inspect the Shared public API
- **WHEN** callers inspect `framework.shared` and `framework.shared.json`
- **THEN** `stable_json_dumps` is available and `canonical_json` is absent

### Requirement: Layered conversion and hashing primitives
The Shared framework SHALL keep JSON-compatible conversion, stable serialization, structured-value hashing, text hashing, and byte hashing as distinct operations with explicit composition.

#### Scenario: Convert a runtime value without hashing it
- **WHEN** a caller passes supported runtime values to `to_jsonable`
- **THEN** the caller receives an inspectable JSON-compatible value rather than a digest

#### Scenario: Hash a structured value
- **WHEN** a caller passes a structured value to `stable_hash`
- **THEN** the system hashes the UTF-8 bytes of its `stable_json_dumps` representation with SHA-256

#### Scenario: Hash text and bytes explicitly
- **WHEN** callers hash equivalent UTF-8 text through `hash_text` and bytes through `hash_bytes`
- **THEN** both operations produce the same SHA-256 digest while preserving explicit input-type boundaries

### Requirement: Durable canonicalization boundaries remain unchanged
The cleanup SHALL NOT change Harness TaskPlan canonical JSON or existing Workflow manifest, DataBuffer, and checkpoint checksum byte contracts.

#### Scenario: Use TaskPlan canonical JSON
- **WHEN** the durable TaskPlan store serializes a TaskPlan payload
- **THEN** it continues to use the TaskPlan-owned `freeze_json` and canonical byte contract

#### Scenario: Verify existing Workflow hashes
- **WHEN** Workflow manifest, DataBuffer, or checkpoint code computes or verifies an existing hash
- **THEN** it continues to use its current format without migration or checksum drift from this change
