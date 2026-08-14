## ADDED Requirements

### Requirement: Protected ownership requires lifecycle authority to retire
The Harness SHALL retire a run, evidence, replay, report, or publication logical reference only from an exact tenant-scoped lifecycle authorization. Run, evidence, and replay ownership SHALL require a terminal run plus elapsed record retention; indefinite report or publication ownership SHALL require an explicit publication-retirement authorization. Cache and ephemeral ownership MAY become inactive only at their exact configured expiry.

#### Scenario: Active run remains protected after nominal retention
- **WHEN** a run artifact reaches its retention timestamp but its owning run has no trusted terminal lifecycle authorization
- **THEN** the reference remains active and no GC plan may mark its physical entry deletable

#### Scenario: Terminal retained run becomes releasable
- **WHEN** a trusted terminal-run authorization matches the tenant/run identity and every owning claim has reached its retention timestamp
- **THEN** the governance runtime may retire the matching run/evidence/replay references with a durable controlled reason

#### Scenario: Indefinite publication is not implicitly retired
- **WHEN** an indefinite report or publication reference has no exact publication-retirement authorization
- **THEN** elapsed time alone cannot release it

### Requirement: GC plans are immutable and fully explainable
The system SHALL persist a side-effect-free GC plan containing the catalog snapshot checksum, generation time, policy version, canonical entry and ref, byte size, claim ids, reference ids, active protection evidence, decision reason, decision checksum, and plan checksum. The same catalog snapshot, policy, and timestamp SHALL produce byte-identical ordered plans.

#### Scenario: Protected cross-run entry is planned
- **WHEN** an expired canonical entry still has an active evidence or replay reference from another run
- **THEN** the plan records `keep`, the protected reference identity, and a controlled protection reason without mutating catalog or bytes

#### Scenario: Unreferenced expired entry is planned
- **WHEN** all logical references for an expired entry are inactive and no indefinite retention applies
- **THEN** the plan records one `delete_candidate` with every claim/reference identity needed to explain the decision

### Requirement: Applying a plan revalidates and atomically detaches catalog ownership
Before physical mutation, the governance runtime SHALL persist an exact operation intent and ask the catalog to compare the planned decision with current state under its mutation lock. The catalog SHALL detach the canonical entry and all inactive claims/references only when the decision is still exact; any new or changed ownership SHALL return `stale` and preserve all catalog and physical state.

#### Scenario: Reference is added after planning
- **WHEN** a new protected logical reference is committed after plan generation but before apply
- **THEN** catalog detach returns `stale`, retains the entry and reference, and performs zero physical mutation

#### Scenario: Concurrent executors claim one candidate
- **WHEN** two executors apply the same exact plan item concurrently
- **THEN** one catalog detach succeeds and both callers converge on the same durable operation identity without a second detach

### Requirement: Physical deletion is verified, quarantined, and idempotent
The filesystem lifecycle adapter SHALL accept only an operation-scoped internal Graph artifact deletion request with an exact run binding, canonical ref, checksum, byte size, media type, and catalog detach receipt. It SHALL remove the internal manifest member, atomically quarantine the verified file on the same volume, persist a quarantine receipt, and purge only that quarantined path. It MUST reject arbitrary paths, public report members, links/reparse points, cross-run refs, and checksum/size mismatches.

#### Scenario: Verified candidate is deleted
- **WHEN** an exact detached Graph artifact is applied with explicit executor authorization
- **THEN** its manifest member is removed, bytes are quarantined and purged, and an exact deletion receipt is committed

#### Scenario: Tampered bytes are encountered
- **WHEN** the candidate file no longer matches the planned checksum or byte size
- **THEN** apply fails closed before quarantine and records a typed retryable operation failure without deleting another object

#### Scenario: Apply is repeated after completion
- **WHEN** the same operation is submitted after its completed tombstone exists
- **THEN** the executor returns the original completion and does not touch the filesystem again

### Requirement: GC recovery resumes every committed transition
The GC operation ledger SHALL use compare-and-set states `prepared`, `catalog_detached`, `quarantined`, `purged`, and `completed`, plus controlled `stale` and retryable failure outcomes. Restart SHALL resume from the last durable state without re-planning, widening the target, or deleting an unclaimed ref.

#### Scenario: Crash follows catalog detach
- **WHEN** the process stops after catalog metadata is detached but before physical quarantine
- **THEN** restart recovers the exact entry/claim/reference snapshot from the operation intent and continues only that deletion

#### Scenario: Crash follows quarantine
- **WHEN** the process stops after the file is renamed to its operation quarantine path
- **THEN** restart locates the same quarantine identity, records or reuses its receipt, and completes one purge

### Requirement: GC apply is explicitly authorized and observable
Operator-facing GC apply SHALL require explicit confirmation and an immutable plan checksum. Every plan/apply transition SHALL emit a sanitized durable usage fact with tenant, run, graph/node when available, artifact class, policy version, bytes, state, and controlled reason. `read_only`, `shadow`, and `legacy` modes MUST NOT perform physical purge.

#### Scenario: Apply lacks confirmation
- **WHEN** an operator invokes GC apply without explicit confirmation
- **THEN** the command fails before catalog or filesystem mutation

#### Scenario: Read-only runtime receives apply
- **WHEN** GC apply is requested while governance is configured `read_only`
- **THEN** the runtime rejects the mutation but still permits plan, report, reconcile, and alert inspection
