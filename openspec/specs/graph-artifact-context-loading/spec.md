# graph-artifact-context-loading Specification

## Purpose
TBD - created by archiving change research-graph-artifact-cutover. Update Purpose after archive.
## Requirements
### Requirement: Artifact context requires an approved load plan
The Harness SHALL create an immutable approved load plan from a typed `ContextAssemblyRequest`, accepted graph result lineages, and catalog records before any artifact payload read. Requested refs SHALL be present in accepted lineage and SHALL match tenant, run, graph, artifact class, sensitivity, checksum, media type, byte size, and provenance constraints.

#### Scenario: Arbitrary ref is requested
- **WHEN** a context request names a ref that is not present in the supplied accepted result lineage
- **THEN** planning fails before the artifact port is read

#### Scenario: Catalog and lineage disagree
- **WHEN** a catalog record differs from lineage in scope, checksum, class, media type, or byte size
- **THEN** planning fails with a typed integrity or scope error

### Requirement: Summary, sample, and full modes have distinct read behavior
`summary_only` SHALL use the persisted bounded lineage summary and perform zero physical reads. `sample` SHALL read and verify the artifact, return a deterministic bounded sample marked incomplete, and preserve source/checksum identity. `full` SHALL return the complete verified candidate only under explicit Harness authorization and within all configured budgets.

#### Scenario: Summary-only assembly
- **WHEN** a valid request selects `summary_only`
- **THEN** context contains only summary, completeness, checksum, and ref metadata and the artifact read count remains zero

#### Scenario: Sample assembly
- **WHEN** a valid request selects `sample` for a candidate larger than the sample limit
- **THEN** context contains a deterministic prefix/sample marked `complete=false` and no gate may treat it as complete evidence

#### Scenario: Full assembly
- **WHEN** a valid request explicitly selects `full` and the complete candidate fits byte/token budgets
- **THEN** the verified full candidate is admitted with `complete=true` and exact checksum lineage

### Requirement: Context budgets and deduplication are deterministic
Planning and loading SHALL enforce maximum refs, total loaded bytes, total loaded tokens, and per-sample bytes. Repeated refs and duplicate content checksums SHALL be admitted once in stable order. Exceeding any bound SHALL produce `CONTEXT_BUDGET_EXCEEDED` rather than silently dropping required policy, schema, gate, source, or evidence references.

#### Scenario: Duplicate content refs
- **WHEN** multiple accepted lineages reference the same catalog content identity
- **THEN** the load result contains one context item and charges its bytes/tokens once

#### Scenario: Full load exceeds budget
- **WHEN** the next verified artifact would exceed the request byte or token limit
- **THEN** loading fails deterministically and returns no partially authorized full context

### Requirement: Sensitive and tampered artifacts fail closed
Secret artifacts SHALL never be loaded. Restricted artifacts SHALL require an explicit allowed sensitivity and purpose. Every sample/full read SHALL revalidate wrapper schema, run binding, candidate checksum, canonical byte size, and media type before returning content.

#### Scenario: Secret artifact
- **WHEN** an accepted lineage points to a catalog record classified as secret
- **THEN** the plan is rejected and no artifact body is read

#### Scenario: Artifact bytes are tampered
- **WHEN** physical bytes no longer match the catalog and lineage checksum
- **THEN** loading raises a typed read-back failure and admits no sample or full content

### Requirement: Context fingerprint is stable and replayable
An approved plan and its load result SHALL carry deterministic checksums over request identity, ordered refs, summaries or verified content identities, completeness, actual bytes/tokens, purpose, and policy version. The final context fingerprint SHALL be recorded for graph lineage/replay and SHALL be identical after restart when inputs are unchanged.

#### Scenario: Context replay
- **WHEN** the same approved request is rebuilt from durable lineage and catalog records after restart
- **THEN** its plan checksum, load-result checksum, and context fingerprint equal the original without producer calls

### Requirement: Approved context load usage is durably accounted
Production context loading SHALL commit one sanitized usage fact after exact load-result verification and before returning admitted context. The fact SHALL bind tenant/run/graph/node, plan checksum, result checksum, purpose, load mode, policy version, actual loaded bytes/tokens, and outcome. Repeating the same plan/result SHALL be idempotent, and usage failure in governed production modes SHALL fail the load with a typed sanitized error.

#### Scenario: Full context load succeeds
- **WHEN** an approved full load verifies all artifacts and fits its budgets
- **THEN** one usage fact records exact loaded bytes/tokens before the context result is returned

#### Scenario: Summary-only load is repeated after restart
- **WHEN** the same summary-only plan/result is rebuilt after restart
- **THEN** the original usage identity is reused and summary bytes/tokens are charged once

#### Scenario: Usage ledger is unavailable
- **WHEN** a production governed context load succeeds physically but its durable usage fact cannot be committed
- **THEN** no accounted context result is returned and the failure contains no artifact body
