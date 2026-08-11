## ADDED Requirements

### Requirement: Source and result snapshots are immutable and integrity bound
Every compaction attempt SHALL reference an immutable source snapshot. A changed result SHALL be written as a distinct immutable result snapshot whose checksum covers ordered group identities, member/source refs, protection state, policy/task binding, materialization revision, and physical-admission identity. A failed attempt MUST NOT overwrite or relabel the source snapshot.

#### Scenario: Source snapshot is modified after planning
- **WHEN** source group content or refs change after a plan is created
- **THEN** plan application fails its source checksum precondition

#### Scenario: Verification fails
- **WHEN** any post-compaction gate fails
- **THEN** the result may be retained as rejected diagnostic evidence but cannot become the active verified snapshot

### Requirement: Compaction records contain complete bounded evidence
A versioned `ContextCompressionRecord` SHALL bind run/step ids, source/result snapshot ids and checksums, plan id and policy revision, ordered action results, before/after physical token counts, retained/removed/replaced/protected group ids, reconstruction/source/summary refs, loss report, versioned gate evidence, aggregate verdict, model/profile/tokenizer/normalizer revisions, reason code, and timestamp. It MUST exclude prompt, evidence, summary, tool-argument, and provider-body text.

#### Scenario: Verified record is written
- **WHEN** a result snapshot passes aggregate VERIFY
- **THEN** its record contains every required identity/count/gate field and the aggregate verdict references the same result checksum

#### Scenario: Record omits gate evidence
- **WHEN** a record claims `VERIFIED` without complete versioned gate refs and checksums
- **THEN** integrity validation and replay classify it as unverified

### Requirement: Canonical durable events describe every transition
Harness SHALL project `context_compaction_planned`, `context_compaction_action_applied`, `context_summary_candidate_created`, `context_compaction_verified`, and `context_compaction_rejected` through the existing canonical event/transcript owner. Events MUST reference durable snapshot/plan/record/artifact ids and bounded verdict metadata, and MUST NOT create a second permanent context event store.

#### Scenario: Verified transition is committed
- **WHEN** aggregate VERIFY passes
- **THEN** the verified event references source snapshot, result snapshot, compaction record, gate evidence, and physical admission evidence before the result can authorize dispatch

#### Scenario: Event sink fails before commit
- **WHEN** the canonical verified event cannot be durably appended
- **THEN** the result snapshot is not treated as active for provider dispatch or recovery

### Requirement: Replay validates rather than recomputes decisions
Replay SHALL load the pinned snapshots, plan, action results, record, policy/profile/tokenizer revisions, and gate evidence; verify checksums and cross-references; and expose the recorded decision without invoking an LLM, re-running compaction, calling tools, writing memory, or publishing artifacts.

#### Scenario: Valid verified record is replayed
- **WHEN** all pinned refs, versions, checksums, and aggregate gate evidence validate
- **THEN** replay reports `versioned_verified_evidence` and reconstructs the recorded source-to-result decision with `side_effects_replayed=false`

#### Scenario: Summary artifact is unavailable
- **WHEN** replay cannot resolve the summary artifact or its expected checksum
- **THEN** replay reports a typed integrity failure and does not trust the result snapshot

### Requirement: Legacy compression evidence is non-authoritative
Legacy snapshots and `CompressionRecord` values MAY remain readable for inspection, but records based on fabricated summary refs, estimated halving, missing plan/action details, or unversioned gate booleans SHALL be classified `legacy_unverified`. They MUST NOT authorize recovery, replayed provider dispatch, or publication.

#### Scenario: Legacy record is inspected
- **WHEN** replay reads an older record containing only source level, target level, summary ref, preserved refs, and boolean gate results
- **THEN** it exposes those fields for audit with `verification_status=legacy_unverified`
- **AND** it performs no side effects
