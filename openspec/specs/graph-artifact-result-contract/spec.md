# graph-artifact-result-contract Specification

## Purpose
TBD - created by archiving change graph-artifact-result-contract. Update Purpose after archive.
## Requirements
### Requirement: Harness owns one typed node result envelope
The system SHALL construct every graph candidate result from a trusted Harness binding and an immutable exact-schema `NodeResultEnvelope`; worker candidate content MUST NOT set or override run, graph, node, attempt, routing, gate, publication, policy, persistence, or authorization fields.

#### Scenario: Worker candidate contains a reserved control field
- **WHEN** a candidate mapping contains `run_id`, `node_id`, `route`, `gate_decision`, `publication`, or another reserved control field
- **THEN** envelope construction fails with `result_schema_invalid`
- **AND** no caller-supplied value becomes Harness control state

#### Scenario: Valid candidate is repeated
- **WHEN** the same trusted binding, candidate, policy snapshot, and timestamp are evaluated repeatedly
- **THEN** canonical candidate bytes, checksum, persistence decision, and serialized envelope are identical

### Requirement: Result contracts validate exact identity and bounded content
The system SHALL validate required identity, exact version references, SHA-256 digests, UTC timestamps, non-negative sizes, finite summary and projection bounds, artifact run scope, cache dependency identity, and exact serialized keys before accepting a result contract.

#### Scenario: Required field is absent or unknown
- **WHEN** a serialized result model omits a required field or contains an unknown field
- **THEN** deserialization fails closed with `result_schema_invalid`

#### Scenario: Summary exceeds its configured bound
- **WHEN** a summary exceeds the configured byte or token limit
- **THEN** result construction fails with `result_too_large`
- **AND** the implementation does not silently truncate it

#### Scenario: Artifact record crosses the result run scope
- **WHEN** an artifact record bound to a different tenant, run, graph, node, or attempt is attached to an envelope
- **THEN** envelope validation fails with `artifact_scope_mismatch`

### Requirement: Persistence policy is deterministic and Harness controlled
The system SHALL compute `inline`, `artifact`, `cache`, or `omitted` from a validated candidate classification and immutable policy configuration using controlled reason codes; worker output MUST NOT select the mode, retention, context policy, required status, or policy version.

#### Scenario: Small non-sensitive control result
- **WHEN** a non-reusable optional control result is within the inline byte limit and its projection satisfies all structural bounds
- **THEN** the policy selects `inline` with `below_inline_threshold`

#### Scenario: Durable evidence result
- **WHEN** a result is evidence or is required for replay or publication
- **THEN** the policy selects `artifact` with a durable reason regardless of the inline threshold

#### Scenario: Reusable deterministic result has complete identity
- **WHEN** a side-effect-free reusable candidate provides an exact dependency digest and unexpired cache identity
- **THEN** the policy selects `cache` with `reusable_deterministic_result`

#### Scenario: Required result exceeds quota
- **WHEN** a required result cannot fit the supplied run byte or artifact-count budget
- **THEN** policy evaluation fails with `artifact_quota_exceeded`
- **AND** it does not return an omitted success

#### Scenario: Optional result exceeds quota
- **WHEN** an optional non-audit result cannot fit the supplied run budget
- **THEN** the policy returns `omitted` with `quota_exceeded`

### Requirement: Sensitive and oversized candidates fail closed
The system SHALL reject secret-classified candidates, private context, hidden prompts, credential-like keys, non-canonical values, and content over the configured artifact maximum before any persistence decision can authorize a write or context projection.

#### Scenario: Candidate includes a secret-like key
- **WHEN** a candidate or inline projection contains a key such as `api_key`, `authorization`, `password`, `private_context`, or `raw_prompt`
- **THEN** evaluation fails with `sensitive_payload_rejected`
- **AND** the serialized error does not include the secret value

#### Scenario: Candidate exceeds the artifact maximum
- **WHEN** canonical candidate bytes exceed `max_artifact_bytes`
- **THEN** evaluation fails with `result_too_large`

### Requirement: Persistence configuration is bounded and versioned
The system SHALL use an immutable `GraphArtifactPersistenceConfig` with bounded thresholds, run quotas, tenant quotas, per-`ArtifactClass` quotas, context limits, cache TTL, five-class retention durations, governance alert thresholds, controlled rollout mode, exact current policy version, and explicitly readable rollback policy versions.

#### Scenario: Configuration uses an out-of-range value
- **WHEN** any configured byte, count, ratio, backlog, stampede, TTL, or retention value is below its minimum or above its maximum
- **THEN** configuration construction fails with `result_schema_invalid`

#### Scenario: Aggregate limits are inconsistent
- **WHEN** a configured run limit exceeds its tenant limit or an artifact-class limit exceeds the tenant limit
- **THEN** configuration construction fails before production composition

#### Scenario: Rollback policy is not readable
- **WHEN** a caller selects a policy version absent from the configured readable policy versions
- **THEN** policy construction fails closed as an unsupported version

#### Scenario: Rollout mode is supplied by worker content
- **WHEN** a worker candidate includes a rollout mode, quota override, retention value, alert threshold, or policy version field
- **THEN** result construction rejects the candidate instead of changing configuration

### Requirement: Result failures have stable sanitized serialization
The system SHALL represent result-contract failures using controlled error codes and sanitized structured details suitable for durable events; serialized failures MUST NOT contain candidate bodies, prompts, credentials, private context, filesystem paths, or raw exception text.

#### Scenario: Error is serialized for an event
- **WHEN** a schema, size, quota, write, read-back, scope, cache, or context-budget failure is converted to an event payload
- **THEN** the payload contains the stable code, retryability, bounded message, and sanitized scalar details only
