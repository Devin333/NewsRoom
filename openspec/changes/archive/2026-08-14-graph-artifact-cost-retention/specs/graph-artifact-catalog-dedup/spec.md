## MODIFIED Requirements

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

## ADDED Requirements

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
