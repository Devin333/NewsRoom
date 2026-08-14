# graph-artifact-catalog-dedup Specification

## Purpose
TBD - created by archiving change graph-artifact-catalog-dedup. Update Purpose after archive.
## Requirements
### Requirement: Verified canonical catalog registration
The Harness artifact catalog SHALL register only an `ArtifactRecord` whose read-back verification receipt exactly matches tenant scope, physical ref, checksum, byte size, and media type. It SHALL derive the canonical physical identity from tenant scope, checksum, media type, and producer revision.

#### Scenario: Verified object is registered
- **WHEN** a caller registers an artifact with an exact read-back verification receipt
- **THEN** the catalog returns a canonical entry and an initial logical reference

#### Scenario: Unverified or mismatched object is rejected
- **WHEN** any receipt field differs from the artifact record or the receipt is missing
- **THEN** registration fails closed with a stable graph artifact error and no catalog state changes

### Requirement: Physical deduplication and immutable logical identity
The catalog SHALL store one canonical physical entry for each dedup identity and SHALL bind each tenant/run/artifact logical identity to exactly one content identity. Each logical claim SHALL retain its own artifact class, sensitivity, retention, and replay/publication requirements while resolving to the canonical physical ref. Re-registering the same logical identity and immutable metadata with a later verification time SHALL be idempotent; attempting to bind it to different content or metadata SHALL fail without replacing existing state.

#### Scenario: Same content is reused across runs
- **WHEN** two verified records in the same tenant have the same checksum, media type, and producer revision but different run identities
- **THEN** both logical references resolve to one canonical physical entry and unique physical bytes are counted once

#### Scenario: Logical identity conflicts
- **WHEN** an existing tenant/run/artifact identity is registered with a different checksum or physical identity
- **THEN** registration fails with `result_identity_conflict` and preserves the original binding

### Requirement: Explicit logical reference ownership
The catalog SHALL store immutable, uniquely identified logical references for run, report, evidence, publication, replay, cache, and ephemeral ownership. Adding the same reference SHALL be idempotent, and removing a reference SHALL require an exact tenant and reference identity match.

#### Scenario: Cross-run reference protects canonical bytes
- **WHEN** a second run adds an evidence or replay reference to an existing canonical entry
- **THEN** both runs list the entry through their logical references and the physical entry remains protected

#### Scenario: Cross-tenant reference is rejected
- **WHEN** a logical reference tenant does not match the canonical entry tenant
- **THEN** the catalog rejects the mutation without changing reference state

### Requirement: Reference-safe deterministic GC planning
The catalog SHALL expose side-effect-free GC planning from an immutable catalog snapshot. A plan SHALL include exact claim/reference evidence and SHALL never mark an entry deletable while it has an active logical reference, an indefinite retention, a future expiry, or unresolved replay/publication/evidence/report/run protection. Cache or ephemeral expiry SHALL NOT override another active protected reference.

#### Scenario: Expired unreferenced entry becomes a delete candidate
- **WHEN** an entry has expired and has no active references at the planning timestamp
- **THEN** the deterministic plan marks it `delete_candidate` with its canonical ref, claim/reference evidence, snapshot checksum, and controlled reason

#### Scenario: Replay reference prevents deletion
- **WHEN** an expired entry still has a replay reference without exact lifecycle retirement
- **THEN** the plan keeps it and records the replay reference identity as protection evidence

#### Scenario: Planning is repeated from one snapshot
- **WHEN** planning uses the same catalog snapshot, policy version, and timestamp
- **THEN** ordered decisions, decision checksums, and plan checksum are identical

### Requirement: Restart-safe exact catalog persistence
The Local JSON adapter SHALL persist exact-schema catalog state atomically, serialize concurrent mutations, validate its integrity checksum, reject unsupported versions, path escape, links/reparse points, malformed identities, and tampered state, and return records in deterministic order.

#### Scenario: Concurrent dedup registration is serialized
- **WHEN** parallel callers register the same verified content and distinct logical run identities
- **THEN** restart yields one canonical entry and all logical references without lost updates

#### Scenario: Tampered or linked state is rejected
- **WHEN** the catalog state checksum is altered or its path resolves through a link/reparse point
- **THEN** the adapter fails closed before returning or mutating catalog records

### Requirement: Reconciliation exposes drift without implicit repair
The catalog SHALL produce a stable reconciliation plan for orphan entries, dangling logical identities, dangling references, identity conflicts, missing physical objects, unregistered physical objects, and physical identity mismatches. Reconciliation SHALL be side-effect-free, SHALL accept only caller-supplied verified physical inventory, and SHALL NOT synthesize a physical verification receipt or delete metadata.

#### Scenario: Dangling reference is reported
- **WHEN** persisted catalog state contains a reference to a missing canonical entry
- **THEN** reconciliation reports the reference and leaves state unchanged

#### Scenario: Clean restart reports no drift
- **WHEN** all identities and references resolve to exact canonical entries after restart
- **THEN** reconciliation reports a clean catalog

#### Scenario: Physical write completed before catalog registration
- **WHEN** verified physical inventory contains an object that has no canonical catalog entry
- **THEN** reconciliation reports `unregistered_physical_object` without deleting the bytes

#### Scenario: Catalog entry has no verified physical object
- **WHEN** a canonical catalog entry has no matching physical inventory receipt
- **THEN** reconciliation reports `missing_physical_object` without inventing a replacement ref

### Requirement: Backend-neutral framework port
The Harness catalog protocol and contracts SHALL NOT import filesystem, database, Research business, or vendor SDK modules. Infrastructure adapters SHALL implement the same observable registration, lookup, reference, GC planning, and reconciliation behavior.

#### Scenario: Framework dependency boundary is checked
- **WHEN** architecture validation scans `framework/harness/artifacts`
- **THEN** no infrastructure or database SDK dependency is present

### Requirement: Lifecycle reference release is exact and authorized
The catalog SHALL remove a protected reference only from an exact tenant/reference identity plus a validated lifecycle authorization whose owner and policy match the reference. Repeating the same retirement SHALL be idempotent; conflicting scope, lifecycle, or policy evidence SHALL fail without mutation.

#### Scenario: Terminal run reference is released
- **WHEN** an authorized lifecycle request proves the owning run is terminal and the logical claim retention has elapsed
- **THEN** the exact run/evidence/replay reference is removed and an immutable retirement receipt is returned

#### Scenario: Wrong tenant attempts retirement
- **WHEN** a retirement request tenant differs from the logical reference tenant
- **THEN** the catalog rejects it and preserves the reference

### Requirement: GC detach is an atomic compare-and-delete lease
The catalog SHALL accept only an exact persisted GC plan decision and SHALL re-evaluate current entry, claims, references, expiry, and protection under the catalog mutation lock. On an exact eligible match it SHALL atomically remove the live entry plus its inactive claims/references and return a complete detach receipt. On any difference it SHALL return stale and preserve state.

#### Scenario: Exact candidate is detached
- **WHEN** the persisted decision still exactly matches an expired unreferenced canonical entry
- **THEN** the catalog removes its live metadata in one atomic state write and returns every record needed for physical recovery and tombstoning

#### Scenario: Detach state write fails
- **WHEN** catalog persistence fails while applying the detach mutation
- **THEN** no partial entry/claim/reference removal becomes visible and physical deletion is not authorized
