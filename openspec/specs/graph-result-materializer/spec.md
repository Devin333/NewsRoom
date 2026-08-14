# graph-result-materializer Specification

## Purpose
TBD - created by archiving change graph-result-materializer. Update Purpose after archive.
## Requirements
### Requirement: Canonical policy-controlled materialization
The Harness SHALL materialize every `NodeResultRequest` through one bounded service that canonicalizes the candidate, evaluates `PersistencePolicy` without side effects, and returns an immutable `NodeResultEnvelope` whose metrics, checksum, mode, and refs agree exactly.

#### Scenario: Small control result is inline
- **WHEN** a valid control candidate is below the configured inline threshold
- **THEN** the materializer returns an `inline` envelope with no artifact or cache refs and the configured projection only

#### Scenario: Large result becomes an artifact
- **WHEN** a candidate exceeds the inline threshold or is required evidence, transcript, report, replay, or publication data
- **THEN** the materializer reserves quota, writes the artifact, verifies read-back, registers the catalog entry, and returns an `artifact` envelope

### Requirement: Quota reservation and settlement
The materializer SHALL reserve estimated candidate bytes and logical object count before artifact/cache writes, use an idempotency key derived from the attempt identity, bind the reservation to trusted tenant/run/graph/node, artifact class, retention class, and policy version, and settle exactly once with actual bytes and outcome. The quota authority SHALL enforce run, tenant, and tenant-plus-artifact-class limits in one transaction. A required durable result SHALL fail closed when any dimension rejects reservation; an optional result SHALL return an explicit `omitted` envelope.

#### Scenario: Required quota exhaustion
- **WHEN** a required artifact cannot reserve its configured run, tenant, or artifact-class bytes/count
- **THEN** no durable write occurs and the materializer raises `ARTIFACT_QUOTA_EXCEEDED`

#### Scenario: Optional quota exhaustion
- **WHEN** an optional large result cannot reserve any configured quota dimension
- **THEN** the materializer returns an `omitted` envelope with no refs and an omission usage fact

#### Scenario: Reservation scope disagrees
- **WHEN** a quota adapter returns a reservation whose graph/node, class, retention, or policy identity differs from the trusted request
- **THEN** the materializer fails closed before writing candidate bytes

### Requirement: Verified artifact persistence
For artifact mode, the materializer SHALL bind the artifact port to the request run, write a bounded graph-result payload envelope, read it back, re-canonicalize the candidate using the original media type, and register the verified `ArtifactRecord` through `ArtifactCatalogPort` only after checksum, byte-size, media-type, and scope checks succeed.

#### Scenario: Read-back tampering
- **WHEN** the returned artifact payload differs from the candidate checksum or byte size
- **THEN** the materializer raises `ARTIFACT_READBACK_FAILED`, settles the reservation as failed, and does not register a catalog entry

#### Scenario: Catalog registration failure
- **WHEN** physical write and read-back succeed but catalog registration fails
- **THEN** the materializer raises a stable catalog/materialization error, settles the reservation as failed, and does not return a successful envelope

### Requirement: Cache persistence and verification
For cache mode, the materializer SHALL derive a tenant-scoped deterministic cache identity from candidate checksum, dependency digest, media type, and policy version; write and read back through `ResultCachePort`; and create a `CacheRef` only after exact verification.

#### Scenario: Reusable result is cached
- **WHEN** a side-effect-free request is eligible for cache mode and quota is available
- **THEN** the materializer returns a cache ref with tenant scope, dependency digest, policy version, and bounded expiry

### Requirement: Attempt idempotency and conflict safety
The materializer SHALL persist the first envelope for `(tenant_id, run_id, graph_id, node_id, attempt_id)`. Repeating the same candidate SHALL return the original envelope without a second logical ref or quota charge; presenting a different candidate or immutable policy identity SHALL fail with `RESULT_IDENTITY_CONFLICT`.

#### Scenario: Retry after successful materialization
- **WHEN** the same attempt request is submitted again with the same candidate and policy identity
- **THEN** the original envelope is returned and no duplicate artifact/catalog/cache claim is created

#### Scenario: Conflicting retry
- **WHEN** the same attempt identity is submitted with a different candidate checksum
- **THEN** the materializer rejects it with `RESULT_IDENTITY_CONFLICT` and preserves the original envelope

### Requirement: Failure observability and boundary
The materializer SHALL expose structured success, omission, and failure observations containing only bounded identity, mode, byte, reservation, and reason fields. It SHALL not include candidate payloads, secret fields, GraphRuntime routing decisions, checkpoint writes, or infrastructure SDK dependencies.

#### Scenario: Optional debug omission is observable
- **WHEN** an optional debug result is omitted because of quota
- **THEN** the observation records omission reason, candidate byte size, and attempt identity without recording the debug payload

#### Scenario: Framework boundary is checked
- **WHEN** architecture validation scans the materializer and its ports
- **THEN** no `infrastructure`, database SDK, Research business, or vendor adapter import is present

### Requirement: Materialization cost facts are durable and exactly once
The materializer SHALL commit a sanitized durable usage fact for inline, artifact, cache, omitted, and failed outcomes. Artifact/cache settlement and its fact SHALL be transactionally consistent; retrying one attempt/outcome SHALL not add a second charge or fact. The best-effort diagnostic callback MUST NOT be used as the cost authority.

#### Scenario: Artifact succeeds
- **WHEN** write, read-back, catalog registration, settlement, and attempt commit succeed
- **THEN** one durable fact records exact logical/physical bytes, class, policy, reservation, and success without candidate content

#### Scenario: Read-back fails
- **WHEN** physical bytes fail checksum or size verification
- **THEN** failed settlement releases quota and one durable failure fact records the controlled read-back error

#### Scenario: Existing attempt is recovered
- **WHEN** an already committed attempt is materialized again after restart
- **THEN** the original envelope and existing usage identity are reused without another quota charge or success fact

### Requirement: Cache facts distinguish lookup from verification
Cache governance SHALL record explicit lookup `hit` or `miss` separately from cache write and read-back verification. A write followed by verification MUST NOT be counted as a worker-saving cache hit.

#### Scenario: Cache entry is only written and verified
- **WHEN** a new reusable candidate is stored and read back after worker execution
- **THEN** usage records cache write/verification but does not increment cache hit count
