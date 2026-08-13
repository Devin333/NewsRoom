# harness-task-plan Specification

## Purpose
TBD - created by archiving change harness-dynamic-task-planning. Update Purpose after archive.
## Requirements
### Requirement: Dynamic stage plan candidates are explicit and candidate-only

The Harness runtime SHALL provide a versioned `PlanCandidate` contract for an explicitly registered dynamic stage. A candidate MUST identify the run, workflow, stage, frozen graph checksum, input context references, task definitions, required output roles, and candidate checksum. A candidate MUST be treated as untrusted worker content until deterministic validation and Harness acceptance complete.

#### Scenario: LLM returns a valid candidate

- **WHEN** a registered dynamic stage invokes the configured plan builder and receives a candidate with valid task ids, dependencies, input refs, output contracts, and capability hints
- **THEN** Harness MUST persist the candidate reference and validate it before any task is dispatched
- **AND** the candidate MUST NOT itself change the outer graph or activate a worker

#### Scenario: Candidate contains an executable control field

- **WHEN** a candidate contains `route`, `next_step`, `quality_passed`, `publish_artifact`, `write_memory`, `halt_workflow`, `worker_ref`, or an arbitrary callable reference
- **THEN** Harness MUST reject the candidate with a typed validation reason
- **AND** no task queue record, worker call, or stage-success transition may be created

#### Scenario: Candidate graph checksum is stale

- **WHEN** a candidate graph checksum differs from the frozen graph checksum of the current run
- **THEN** Harness MUST reject the candidate before plan acceptance
- **AND** the rejection MUST include both checksum references without invoking a task worker

### Requirement: TaskPlan policy bounds every dynamic stage

Every dynamic stage SHALL resolve one pinned `TaskPlanPolicy` before candidate generation. The policy MUST declare allowed capabilities, subagents, tools, memory namespaces, output roles, deterministic gates, task/depth/parallelism limits, retry/replan limits, and plan-builder budget limits. A candidate MUST NOT widen or replace policy values.

#### Scenario: Dynamic stage has no policy

- **WHEN** a frozen graph references a dynamic stage without a registered compatible policy
- **THEN** preflight MUST fail before `RUN_CREATED` or plan-builder invocation
- **AND** the run MUST expose a typed missing-policy diagnostic

#### Scenario: Candidate requests a disallowed tool

- **WHEN** a candidate requests a tool outside the stage policy allowlist
- **THEN** candidate validation MUST fail before dispatch
- **AND** Harness MUST NOT treat the request as an authorization grant

#### Scenario: Candidate exceeds task or depth limits

- **WHEN** a candidate contains more tasks or dependency depth than the pinned policy allows
- **THEN** Harness MUST reject the entire candidate atomically
- **AND** no subset of tasks may be dispatched as a partial plan

### Requirement: TaskPlan validation SHALL be deterministic and complete

The TaskPlan validator SHALL validate schema, unique ids, dependency references, cycle freedom, reachability, stage boundaries, dataflow references, required output roles, output conflicts, deterministic gate references, capability binding availability, tool/memory policy, and aggregate budget before plan acceptance. Validation MUST be pure with respect to time, network, random state, and mutable global state.

#### Scenario: Candidate contains a dependency cycle

- **WHEN** task A depends on task B and task B depends on task A
- **THEN** validation MUST return a stable cycle reason code
- **AND** Harness MUST persist no accepted plan and dispatch no task

#### Scenario: Candidate omits a required output role

- **WHEN** no reachable task produces one of the policy's required output roles
- **THEN** validation MUST fail with the missing role and producer diagnostics
- **AND** the dynamic stage MUST remain in a controlled failure state

#### Scenario: Candidate has an undeclared output collision

- **WHEN** two concurrent task definitions write the same output role without a policy-approved deterministic aggregator
- **THEN** preflight MUST reject the plan
- **AND** last-writer-wins MUST NOT be selected implicitly

### Requirement: Accepted TaskPlans are immutable and versioned

Harness SHALL accept a valid candidate as an immutable `ValidatedTaskPlan` with a plan id, monotonically increasing version, source candidate reference, pinned policy reference, frozen graph checksum, resolved tasks, normalized limits, and plan checksum. Any accepted change MUST create a new plan version rather than mutating an existing plan.

#### Scenario: Initial candidate is accepted

- **WHEN** all candidate and policy validations pass
- **THEN** Harness MUST commit a `PLAN_ACCEPTED` event for version 1 before dispatch
- **AND** the accepted plan checksum MUST be available to every task instance created from that plan

#### Scenario: Accepted plan is changed

- **WHEN** a repair or replan needs to add a replacement task
- **THEN** Harness MUST create a new version with a parent plan reference and new checksum
- **AND** the previous version and its task results MUST remain readable for replay

#### Scenario: Plan version is not monotonic

- **WHEN** a submitted plan or patch version is not the next valid version for the stage projection
- **THEN** Harness MUST reject it as a stale or conflicting plan
- **AND** the current plan projection MUST remain unchanged

### Requirement: Capability hints resolve only through Harness-controlled bindings

TaskPlan candidates SHALL express a logical `worker_capability` hint, not an implementation, handler, callable, or unpinned worker version. Harness MUST resolve each hint through a pinned registry and stage policy to one compatible worker or `SubAgentSpec`, then compute the final tool, memory, context, and budget boundary.

#### Scenario: Capability resolves uniquely

- **WHEN** a candidate capability is allowlisted and resolves to one registered compatible worker binding
- **THEN** Harness MUST record the exact binding reference in `ValidatedTaskPlan`
- **AND** the worker MUST receive only the task context allowed by the resolved policy

#### Scenario: Capability has multiple bindings

- **WHEN** a capability resolves to multiple active worker implementations without an explicit pinned selection policy
- **THEN** plan validation MUST fail closed
- **AND** the candidate MUST NOT choose one by iteration order or LLM preference

#### Scenario: Subagent output tries to route the stage

- **WHEN** a bound subagent returns a routing, quality, publication, memory, or halt field
- **THEN** existing SubAgent/Harness result gates MUST reject or strip the forbidden candidate result according to the established result contract
- **AND** the field MUST NOT influence TaskPlan scheduling or stage outcome

### Requirement: Ready tasks are calculated deterministically and dispatched within bounds

The TaskPlan scheduler SHALL mark a task ready only when all required dependencies have durable successful results, all input references resolve, policy and binding checks remain valid, and budget reservation succeeds. Ready tasks MUST be ordered deterministically and physical dispatch MUST honor stage `max_parallelism`, worker capacity, and run budget.

#### Scenario: Independent tasks become ready together

- **WHEN** two tasks have no dependencies and their inputs and budgets are valid
- **THEN** the scheduler MUST return both in stable priority/depth/id order
- **AND** the dispatcher MAY run them concurrently only within the configured parallelism bound

#### Scenario: Dependent task waits for its predecessor

- **WHEN** task C depends on task A and A has not durably completed
- **THEN** C MUST NOT be ready or dispatched
- **AND** A's accepted result MUST be committed before C can become ready

#### Scenario: Budget reservation fails

- **WHEN** a ready task cannot reserve its normalized budget
- **THEN** Harness MUST not dispatch that task or any task whose reservation would exceed the remaining bound
- **AND** the stage MUST follow the explicit budget-exhaustion policy

### Requirement: Queue records are execution projections, not TaskPlan authority

The runtime MAY materialize a ready task into the existing generic worker queue, but queue records MUST carry plan/task identity references and MUST NOT become the source of truth for DAG dependencies, plan versions, accepted output, or replay state. Plan projection and durable events SHALL remain authoritative.

#### Scenario: Queue task is duplicated

- **WHEN** the same `task_instance_id` is delivered by the queue more than once
- **THEN** Harness MUST use attempt, fencing, and idempotency identity to accept at most one committed result
- **AND** duplicate delivery MUST NOT create a second logical task completion

#### Scenario: Queue record is lost before worker execution

- **WHEN** a queue record disappears after `TASK_READY` but before a committed result
- **THEN** recovery MUST recompute readiness from the TaskPlan projection
- **AND** it MAY recreate a queue projection without changing plan version or task definition identity

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

### Requirement: Stage aggregation is deterministic and role-complete

A dynamic stage SHALL expose outputs only through a registered deterministic aggregator. The aggregator MUST consume accepted task result references in stable order, enforce output roles and schema, reject missing or conflicting roles, and produce a checksum-bound stage output projection.

#### Scenario: Research roles are complete

- **WHEN** accepted task results provide every required Research analysis role
- **THEN** the aggregator MUST produce the existing `analysis_branch_refs` contract
- **AND** the fixed `verify_claims` successor MAY consume that reference

#### Scenario: Aggregation has an incomplete role set

- **WHEN** one required output role has no accepted result
- **THEN** aggregation MUST fail with a typed missing-role outcome
- **AND** the stage MUST NOT enter downstream quality or publication steps

#### Scenario: Aggregation sees conflicting outputs

- **WHEN** two accepted tasks claim one role without a declared merge contract
- **THEN** aggregation MUST fail closed
- **AND** it MUST not select a winner based on completion time or queue order

### Requirement: Replan uses bounded immutable PlanPatch versions

Harness SHALL accept a `PlanPatch` only when its `base_plan_version` matches the current projection and every operation is allowed by policy. v1 operations SHALL be limited to adding replacement tasks, skipping eligible pending tasks, and changing dependencies of not-started tasks. Completed, running, committed, required-role, policy, gate, publication, and outer-Graph data MUST remain immutable.

#### Scenario: Replacement patch is accepted

- **WHEN** a failed task has exhausted retry and a patch adds a valid replacement task against the current plan version
- **THEN** Harness MUST create the next plan version and preserve all completed task results
- **AND** the scheduler MUST recompute readiness using the new version

#### Scenario: Patch uses a stale base version

- **WHEN** a patch references a plan version older than the current projection
- **THEN** Harness MUST reject the patch without partial operations
- **AND** no task status or plan checksum may change

#### Scenario: Patch attempts to edit a completed task

- **WHEN** a patch updates dependencies, output, or result refs of a completed task
- **THEN** validation MUST reject the entire patch
- **AND** historical event and output references MUST remain unchanged

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

### Requirement: TaskPlan inspection is security-projected

Authorized inspection SHALL expose stage policy, plan/patch references, versions/checksums, task states, dependency summaries, attempts, budgets, failure reasons, output references, and replay verification. Inspection MUST redact raw prompts, secrets, unauthorized tenant data, and unbounded worker payloads.

#### Scenario: Operator inspects a running plan

- **WHEN** an authorized operator reads a dynamic stage with ready, running, and completed tasks
- **THEN** inspection MUST distinguish those states and expose the current plan version and durable sequence
- **AND** it MUST not expose raw subagent context or hidden prompts

#### Scenario: Unauthorized tenant reads inspection

- **WHEN** an inspection request lacks the required tenant or identity scope
- **THEN** the application service MUST reject the request before reading private task payloads
- **AND** no plan/task content may be returned

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

### Requirement: TaskPlan Verifies Subagent Artifact References

TaskPlan SHALL treat subagent artifact references as evidence owned by the canonical artifact store, not as self-authenticating URI strings. For every non-empty artifact ref, deterministic result verification and replay MUST require an `ArtifactReferenceVerifierPort`, bind the check to `TaskResultRecord.run_id`, and reject the candidate or history when the owner cannot verify the reference. Empty artifact-ref tuples SHALL remain valid and non-subagent result behavior SHALL remain unchanged.

#### Scenario: Worker and transcript repeat a fabricated ref

- **WHEN** a subagent worker result and its durable output document contain the same fabricated artifact URI
- **THEN** TaskPlan MUST reject the result with `task_plan_subagent_artifact_unverified`
- **AND** it MUST NOT append an accepted or rejected TaskResult for that unverified candidate

#### Scenario: Artifact verifier is not configured

- **WHEN** a subagent output contains artifact refs but TaskPlan has no canonical artifact verifier
- **THEN** deterministic result verification or replay MUST fail closed with `task_plan_subagent_artifact_verifier_required`
- **AND** string equality among output, result, and event records MUST NOT satisfy the evidence requirement

#### Scenario: Replay artifact integrity has changed

- **WHEN** a previously recorded artifact ref no longer resolves with the recorded run identity, manifest, checksum, or bytes
- **THEN** TaskPlan replay MUST fail with `task_plan_subagent_artifact_unverified`
- **AND** it MUST NOT report the stage as verified or call the live subagent again
