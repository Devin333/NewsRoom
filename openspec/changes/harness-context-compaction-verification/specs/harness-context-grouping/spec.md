## ADDED Requirements

### Requirement: Context materializes as immutable semantic groups
Harness SHALL materialize semantic context as an ordered tuple of immutable `ContextGroup` values before planning compaction. Every group MUST have a stable group id, typed group kind, ordered member refs, source refs, token-count evidence or a count-ref, protection reasons, reconstruction policy, and schema revision. Raw payload text MUST NOT be the durable group identity.

#### Scenario: Stable materialization
- **WHEN** the same source snapshot, workflow contract, task, authorization state, and policy revision are materialized twice
- **THEN** both materializations have the same ordered group identities and source refs
- **AND** diagnostic metadata does not change group identity

#### Scenario: Unsupported source shape
- **WHEN** an input message, evidence item, tool descriptor, or reference cannot be assigned to a supported group kind without losing order or ownership
- **THEN** materialization fails with a typed validation reason before compaction or provider preparation

### Requirement: Message and role structure is validated before use
Harness SHALL validate group ordering, message role ordering, system/current-task placement, required output-contract presence, and member-reference integrity before a context snapshot can be used. Invalid histories MUST NOT be repaired by silently dropping an offending member.

#### Scenario: Orphan tool result
- **WHEN** a tool-result member has no matching assistant tool-call member in the same transaction
- **THEN** structure verification fails and no result snapshot is promoted

#### Scenario: Required output contract is missing
- **WHEN** the worker contract requires a structured output schema but the materialized context lacks the corresponding protected group
- **THEN** verification fails before provider dispatch

### Requirement: Tool transactions are atomic groups
Each assistant tool call and its ordered tool result or results SHALL be represented as one `TOOL_TRANSACTION` group. A compaction action MUST retain, replace through a lossless durable transaction ref, or remove the entire completed transaction. Pending, failed-with-unhandled-state, or authorization-relevant transactions MUST be protected and MUST NOT be summarized as completed.

#### Scenario: Completed transaction is removed
- **WHEN** policy authorizes removal of a reconstructable completed tool transaction
- **THEN** the action removes every call/result member atomically and records its durable reconstruction ref

#### Scenario: Pending transaction is under pressure
- **WHEN** a pending tool transaction contributes to an over-budget context
- **THEN** the transaction remains protected and the planner selects another allowed action or returns `PROTECTED_CONTEXT_EXCEEDS_WINDOW`

### Requirement: Protected content is explicit and fail closed
Harness SHALL attach versioned protection reasons to system instructions, safety constraints, current task and workflow-step contracts, required output contracts, current retry/replan state, unresolved tool transactions, required evidence/source refs, and control-plane decisions. Neither a planner nor a summary worker MAY remove or weaken a protected group.

#### Scenario: Protected groups alone exceed capacity
- **WHEN** the physical admission verifier reports that protected groups plus required provider fields cannot fit the allowed deployment profile
- **THEN** compaction returns `PROTECTED_CONTEXT_EXCEEDS_WINDOW`
- **AND** no summary call, provider call, or verified result snapshot is authorized

#### Scenario: Request metadata weakens protection
- **WHEN** worker or request metadata claims that a protected group may be dropped
- **THEN** the trusted Harness policy remains authoritative and the override is ignored or rejected

### Requirement: Evidence groups retain provenance and required-citation state
Evidence groups SHALL identify evidence ids, source refs, span refs, lineage refs, required-citation status, query/task binding, and conflict status. Evidence text MAY be replaced only by an action whose result retains the evidence identity and required provenance.

#### Scenario: Required evidence span is retained
- **WHEN** an evidence group contains a span required by the current answer contract
- **THEN** every admissible result retains that span or a verified summary claim with the same supporting evidence and source refs

#### Scenario: Conflicting evidence is compacted
- **WHEN** evidence groups contain an unresolved conflict
- **THEN** compaction retains the conflict marker and both sides' supporting refs rather than selecting a winner
