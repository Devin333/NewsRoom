## MODIFIED Requirements

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

## ADDED Requirements

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
