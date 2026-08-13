## MODIFIED Requirements

### Requirement: Subagent Isolation
Harness SHALL isolate subagents with independent context, private history, explicit handoff payloads, tool allowlists, memory namespaces, and versioned durable transcripts. Subagents MUST NOT read sibling transcripts, raw parent context, hidden prompts, unauthorized memory namespaces, or parent-scoped transcript queries. Every production subagent attempt MUST use an explicitly injected durable transcript store and MUST commit a readable checksum-bound transcript and candidate-output receipt before its result can be accepted; production MUST NOT implicitly construct a fake store.

#### Scenario: Cross-subagent data uses approved handoff
- **WHEN** one subagent output is needed by another subagent
- **THEN** Harness MUST serialize it through an approved handoff schema
- **AND** a gate MUST validate the handoff before the receiving subagent can consume it

#### Scenario: Production subagent attempt completes
- **WHEN** a production subagent returns a successful, failed, or halted candidate outcome
- **THEN** Harness MUST persist one typed attempt receipt bound to parent, child, workflow, stage, task, task instance, attempt, and subagent identity
- **AND** the transcript gate MUST verify the receipt, body checksum, candidate-output checksum, and durable read-back before returning the outcome to TaskPlan verification

#### Scenario: Durable transcript persistence fails
- **WHEN** transcript commit, read-back, size validation, identity validation, or checksum verification fails
- **THEN** Harness MUST reject the original candidate outcome with a stable persistence reason
- **AND** it MUST record a controlled durable parent failure transition without falling back to process-local storage

### Requirement: Trace Checkpoint Replay
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, artifact publication decisions, required subagent transcript/output receipts, and required terminal failure transitions to a durable transcript or event log that can support checkpointing and replay. Gate evidence MUST include the exact gate id and version, deterministic input reference, result reference, pass/fail outcome, stable reason code, aggregate verdict, and resulting scheduler decision before the next state or publication is accepted. Recovery MUST distinguish a durably committed terminal failure from an execution failure whose terminal evidence is absent or uncommitted. Required subagent evidence MUST be resolved and checksum-verified from durable storage without live worker execution.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, subagent receipt, and artifact decision events without calling an LLM

#### Scenario: Recovery resumes after committed VERIFY
- **WHEN** VERIFY evidence and its transition were durably committed before a process crash
- **THEN** recovery MUST use the recorded gate evidence and pinned gate version as scheduler input
- **AND** recovery MUST NOT replace the recorded verdict with current defaults or worker self-evaluation

#### Scenario: Recorded gate evidence is incomplete
- **WHEN** recovery cannot resolve the pinned gate version or verify the recorded gate evidence checksum
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST NOT guess, reclassify the history as passed, or invoke an LLM

#### Scenario: Terminal failure evidence is absent
- **WHEN** recovery observes TaskPlan execution evidence without the required durable `TASK_PLAN_HALTED` transition after a terminal failure
- **THEN** recovery MUST expose a controlled retry, quarantine, or manual-repair state
- **AND** it MUST NOT assume the stage safely halted or continue publication

#### Scenario: Offline replay resolves subagent evidence
- **WHEN** replay encounters a versioned TaskPlan result for a subagent attempt
- **THEN** it MUST resolve and verify the recorded transcript and candidate-output refs against the accepted attempt identity
- **AND** real subagent, tool, retrieval, memory-write, and publication call counts MUST remain zero

#### Scenario: Legacy subagent evidence is unavailable
- **WHEN** replay or inspection requires durable subagent evidence from a pre-v1 process-local transcript record
- **THEN** it MUST return the typed reason `subagent_transcript_legacy_unavailable`
- **AND** it MUST NOT manufacture a readable ref or treat the legacy string as verified evidence

## ADDED Requirements

### Requirement: Durable Subagent Attempt Evidence
Harness SHALL own versioned immutable contracts for subagent context evidence, candidate output, transcript body, typed receipt, and a transcript store port. The production store SHALL atomically publish one run-scoped attempt bundle, SHALL support restart-safe read and verification, and SHALL enforce identical-body idempotency and different-body conflict semantics across threads, instances, and processes.

#### Scenario: Same attempt is committed twice
- **WHEN** two writers commit the same identity with the same context, output, and transcript checksums
- **THEN** both writes MUST return the original durable receipt
- **AND** the parent-scoped query MUST contain one transcript ref

#### Scenario: Same identity has different content
- **WHEN** a writer commits an existing attempt identity with a different document checksum
- **THEN** the store MUST fail with `subagent_transcript_conflict`
- **AND** it MUST leave the originally committed bundle unchanged and readable

#### Scenario: Stored bundle is tampered
- **WHEN** a body, ref, path, schema, size, identity field, or checksum no longer matches its receipt
- **THEN** read or verify MUST fail with a typed corrupt, not-found, size, or identity reason
- **AND** the evidence MUST NOT pass the transcript gate

#### Scenario: Receipt exists before parent result commit
- **WHEN** recovery finds a valid attempt receipt but no committed TaskPlan result
- **THEN** it MUST reconstruct the prior candidate outcome through a read-only recovery path
- **AND** it MUST NOT call the subagent worker or repeat a worker side effect

### Requirement: Bounded Subagent Evidence Content
Subagent transcripts SHALL contain only identity, schema/checksum, timestamps, approved refs, deterministic gate evidence, budget facts, bounded redaction facts, stable warning/error codes, and bounded lifecycle facts. The transcript MUST recursively reject private/raw fields and secret-like values, MUST default to at most `1 MiB`, and MUST reference rather than duplicate full candidate output.

#### Scenario: Transcript candidate contains private or secret content
- **WHEN** a transcript field contains a forbidden nested key or a secret-like credential value
- **THEN** transcript construction or persistence MUST fail closed
- **AND** no transcript body, log event, or metric payload may contain that value

#### Scenario: Transcript exceeds its size limit
- **WHEN** canonical transcript bytes exceed the configured production limit
- **THEN** persistence MUST fail with `subagent_transcript_size_exceeded`
- **AND** the store MUST NOT truncate the transcript and claim a complete receipt

#### Scenario: Parent transcripts are queried
- **WHEN** an authorized inspection service requests refs for one parent run with a bounded limit
- **THEN** the store MUST return a stable, deduplicated, parent-scoped ordering
- **AND** the query MUST NOT expose transcript bodies or refs from another parent run
