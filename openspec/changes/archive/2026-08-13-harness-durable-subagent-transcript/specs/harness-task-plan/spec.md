## MODIFIED Requirements

### Requirement: Task results have bounded attempts and deterministic verification

Every task attempt SHALL have a unique task-instance identity, plan version, worker binding, budget snapshot, and result checksum. Harness MUST validate `HarnessWorkerResult`/`SubAgentResult`, output schema, declared deterministic gates, tool/memory usage, and attempt identity before committing success. A resolved subagent task MUST additionally carry exactly one typed durable attempt receipt; its transcript and candidate output MUST be read back, checksum-verified, and matched to the accepted plan/task/attempt before a successful, failed, or halted result is committed. Non-subagent tasks MUST NOT be required to fabricate transcript evidence.

#### Scenario: Valid result completes a task

- **WHEN** a worker result matches the task identity, output contract, binding, budget, and required deterministic gates
- **THEN** Harness MUST commit the accepted result and task terminal event
- **AND** only then may downstream dependencies be reconsidered

#### Scenario: Result belongs to an old plan version

- **WHEN** a result arrives with a plan version lower than the current stage version and the task is not an accepted committed result
- **THEN** Harness MUST reject the result as stale
- **AND** the current task projection and downstream readiness MUST remain unchanged

#### Scenario: Task retry limit is reached

- **WHEN** a retryable task failure reaches the normalized `max_task_attempts`
- **THEN** the task MUST enter terminal failure or a policy-approved replan state
- **AND** Harness MUST NOT silently create another attempt

#### Scenario: Subagent result has verified durable evidence

- **WHEN** a resolved subagent result carries a receipt whose transcript, output, binding, and attempt identity all verify
- **THEN** the versioned `TaskResultRecord` MUST include the transcript ref/checksum and candidate-output ref/checksum in its checksum projection
- **AND** a successful result MUST use the readable durable candidate-output ref as `result_ref`

#### Scenario: Subagent result has fabricated evidence

- **WHEN** a subagent result carries a missing, unreadable, stale, corrupt, mismatched, or fabricated receipt or output ref
- **THEN** deterministic result verification MUST reject the result before appending an accepted or rejected TaskResult
- **AND** Harness MUST record a controlled parent failure transition with the stable reason

#### Scenario: Failed subagent attempt is recorded

- **WHEN** a subagent worker fails or a deterministic subagent gate halts the attempt and its durable receipt verifies
- **THEN** the rejected result and terminal failure event MUST retain the same transcript/output evidence lineage
- **AND** the candidate output MUST NOT become an accepted downstream result

### Requirement: TaskPlan transitions are durable and replayable

The runtime SHALL record candidate, validation, acceptance, readiness, dispatch, start, retry, result, task terminal, patch, aggregation, verification, and halt transitions in the canonical run event stream. Checkpoints MUST include graph checksum, plan version/checksum, task projection, output references, budget state, replan/retry counters, stream sequence, and versioned TaskResult checksums. Result and terminal events for subagent attempts MUST carry the same transcript and candidate-output refs/checksums as their TaskResult record. Replay MUST use recorded candidate/plan/result/transcript/output evidence and MUST NOT call live LLMs or workers.

#### Scenario: Crash occurs after plan acceptance

- **WHEN** the process crashes after `PLAN_ACCEPTED` but before all queue projections are created
- **THEN** recovery MUST load the accepted plan and recompute missing ready projections deterministically
- **AND** it MUST not generate a new candidate or plan version

#### Scenario: Replay verifies a completed stage

- **WHEN** a completed TaskPlan stage is replayed from its checkpoint and event stream
- **THEN** replay MUST rebuild the same plan/task/output projection and decision checksums
- **AND** it MUST not call the live plan builder, subagent, tool, or queue worker

#### Scenario: Plan evidence is corrupt

- **WHEN** a plan artifact, patch, result ref, transcript ref, candidate-output ref, or checksum cannot be resolved or verified during recovery
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST not mark the stage complete or guess a replacement plan

#### Scenario: Crash occurs after subagent receipt commit

- **WHEN** the process crashes after a subagent receipt is committed but before its TaskResult is appended
- **THEN** recovery MUST reuse that exact receipt and reconstruct the candidate outcome for deterministic TaskPlan verification
- **AND** it MUST not call the subagent worker or create a conflicting attempt body

#### Scenario: Result event is missing after result document persistence

- **WHEN** recovery finds an immutable TaskResult document but its matching result or terminal transition is absent
- **THEN** reconciliation MUST append only the missing transition with the same checksum and projection
- **AND** it MUST not run the worker or generate a new result document

## ADDED Requirements

### Requirement: Durable Subagent Result Lineage

TaskPlan SHALL use a versioned result schema whose subagent evidence fields are authoritative, checksum-bound, and repeated consistently in `TASK_RESULT_ACCEPTED`, `TASK_RESULT_REJECTED`, `TASK_COMPLETED`, and `TASK_FAILED`. The verifier SHALL determine whether evidence is required from the resolved capability binding, not from caller diagnostics.

#### Scenario: Operator follows a completed subagent task

- **WHEN** an authorized operator follows a terminal TaskPlan event to its TaskResult record
- **THEN** the event and record MUST identify the same invocation, task instance, attempt, transcript ref/checksum, and candidate-output ref/checksum
- **AND** each ref MUST resolve through its framework-owned reader within the parent run scope

#### Scenario: Non-subagent task is verified

- **WHEN** the resolved capability is not a subagent
- **THEN** TaskPlan MAY commit the result without transcript evidence after its normal deterministic verification
- **AND** it MUST NOT create placeholder transcript or output receipt fields

#### Scenario: Legacy TaskResult is read

- **WHEN** `TaskResultRecord.from_dict()` reads the prior unversioned result shape
- **THEN** it MUST verify the original checksum projection and preserve the legacy schema identity
- **AND** a later request for required subagent evidence MUST fail with `subagent_transcript_legacy_unavailable` rather than manufacturing evidence
