# graph-artifact-cost-governance Specification

## Purpose
TBD - created by archiving change graph-artifact-cost-retention. Update Purpose after archive.
## Requirements
### Requirement: Quota is enforced across tenant, run, and artifact class
The quota authority SHALL reserve estimated bytes and object count in one transaction against the configured tenant totals, run totals, and tenant-plus-`ArtifactClass` totals. A reservation SHALL carry trusted tenant/run/graph/node identity, artifact class, retention class, policy version, idempotency key, and generation. Exceeding any dimension SHALL reject the reservation without a physical write.

#### Scenario: Tenant quota is exhausted by several runs
- **WHEN** a new reservation fits its run limit but would exceed the aggregate tenant byte or count limit
- **THEN** reservation is rejected and no artifact/cache write or catalog registration occurs

#### Scenario: Artifact-class quota is exhausted
- **WHEN** an evidence reservation fits tenant and run totals but exceeds the tenant evidence-class limit
- **THEN** the evidence reservation is rejected while unrelated artifact classes retain their own available quota

### Requirement: Reservation settlement and reconciliation are exactly once
Successful settlement SHALL replace reserved bytes/count with exact values; failed settlement SHALL release the reservation; pending reservations SHALL remain charged across restart. Repeating an identical settlement SHALL be idempotent, conflicting settlement SHALL fail closed, and reconciliation SHALL release pending usage only from durable evidence that no successful attempt, catalog claim, cache entry, or physical operation exists.

#### Scenario: Settlement is retried after restart
- **WHEN** the same reservation and exact successful settlement are submitted in a new process
- **THEN** aggregate usage is charged once and the original settlement is returned

#### Scenario: Pending reservation has ambiguous outcome
- **WHEN** a pending reservation survives a crash and durable stores cannot prove failure or success
- **THEN** it remains charged and reconciliation reports it for review rather than releasing quota by elapsed time

### Requirement: Cost-relevant usage is durable, idempotent, and sanitized
The system SHALL persist exact-schema usage facts for materialization decisions/outcomes, cache lookup hit/miss, artifact read-back failure, approved context loads, catalog drift, and GC transitions. Fact identity SHALL derive from trusted operation identity and kind. Facts MUST contain only bounded correlation ids, enums, integer bytes/tokens/counts, policy version, checksums or refs, and controlled reason/error codes; they MUST NOT contain artifact bodies, prompts, tool payloads, secrets, paths, or raw exceptions.

#### Scenario: Materialization failure is recorded
- **WHEN** a reserved artifact write or read-back fails
- **THEN** one failed usage fact records its trusted dimensions, attempted bytes, and controlled error code without candidate content

#### Scenario: Context load is retried
- **WHEN** the same approved plan/result checksum is loaded more than once during recovery
- **THEN** the usage ledger contains one context-load fact and charges the exact loaded bytes/tokens once

### Requirement: Daily cost reports are deterministic and multidimensional
The governance runtime SHALL generate an exact-schema report for one UTC day using a catalog snapshot checksum and durable usage watermark. It SHALL report logical bytes/count, unique physical bytes/count, dedup savings ratio, cache hit/miss and nullable hit ratio, expired bytes, failed writes, context-load bytes/tokens, and GC bytes by tenant, run, graph, node, artifact class, and policy version. Stable input snapshot and watermark SHALL produce byte-identical sorted output and checksum.

#### Scenario: Deduplicated content spans runs
- **WHEN** two logical run claims resolve to one canonical physical entry
- **THEN** tenant logical bytes include both claims, global unique physical bytes include the entry once, and scoped groups expose their reachable unique identity without double-counting the global total

#### Scenario: No cache lookup occurred
- **WHEN** a report window contains no explicit cache hit or miss fact
- **THEN** hit and miss counts are zero and `cache_hit_ratio` is null rather than fabricated

#### Scenario: Late fact arrives for a closed day
- **WHEN** a new durable fact changes the usage watermark after a closed-day report was stored
- **THEN** generation creates a new immutable report revision and preserves the earlier report

### Requirement: Governance alerts are deterministic and durable
The alert evaluator SHALL generate stable alert identities for run/tenant quota at or above the configured warning ratio, GC backlog over threshold, any production read-back failure, any catalog reconciliation drift, and cache stampede misses for one trusted cache identity. Re-evaluation SHALL be idempotent, alert acknowledgement SHALL be compare-and-set, and acknowledgement MUST NOT delete source facts.

#### Scenario: Run reaches warning threshold
- **WHEN** charged run bytes or count reaches at least the configured basis-point ratio of its limit
- **THEN** one quota-pressure alert records the dimension, usage, limit, ratio, policy version, and reporting window

#### Scenario: Catalog drift is observed repeatedly
- **WHEN** the same reconciliation issue is evaluated more than once under the same snapshot
- **THEN** one durable drift alert is returned with the original stable identity

### Requirement: Governance queries preserve scope and privacy
Operator report, alert, quota, GC, and reconcile queries SHALL require explicit tenant scope unless an authorized aggregate query is selected. Results SHALL use typed exact schemas and sanitized identifiers. Cross-tenant filters, unknown plan/report identities, malformed dates, and unsupported policy versions SHALL fail without leaking another tenant's metadata.

#### Scenario: Cross-tenant report identity is requested
- **WHEN** a tenant-scoped operator requests a report or alert owned by another tenant
- **THEN** the service returns a scoped not-found or authorization failure without disclosing the other tenant identity
