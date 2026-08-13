## ADDED Requirements

### Requirement: Accepted TaskPlans bind immutable policy identity
Every newly accepted TaskPlan version SHALL record the exact policy reference and canonical policy checksum used for deterministic validation. Initial acceptance and patch acceptance MUST fail closed when the supplied policy reference or checksum differs from the accepted Plan, and a mismatch MUST NOT mutate the Plan, projection, patch evidence, or event stream.

#### Scenario: Patch supplies another exact policy
- **WHEN** a patch request supplies a policy whose exact reference differs from the current Plan policy reference
- **THEN** Harness MUST reject the patch with `task_plan_policy_mismatch`
- **AND** no patch or Plan event and no task projection change may be committed

#### Scenario: Policy content drifts under the same reference
- **WHEN** a patch request supplies the same exact policy reference with a checksum different from the current Plan policy checksum
- **THEN** Harness MUST reject the patch with `task_plan_policy_mismatch`
- **AND** Harness MUST NOT validate patch operations under the drifted policy content

#### Scenario: Legacy Plan has no policy checksum
- **WHEN** an existing Plan payload without `policy_checksum` is replayed
- **THEN** replay MUST preserve its original checksum and projection semantics
- **AND** patch acceptance MUST fail closed unless immutable policy identity can be proven

### Requirement: TaskPlan input references are authorized individually
TaskPlan SHALL use one canonical parser for `task:`, `task://`, and known plain task references across candidate validation, patch validation, scheduling, and replay-related projections. Every task reference MUST resolve to a Plan task and declare that producer in `depends_on`; every external reference MUST be present in both the pinned policy allowlist and current stage context.

#### Scenario: Mixed task and unauthorized external input
- **WHEN** one task declares a valid task dependency and an external input outside the policy allowlist
- **THEN** candidate validation MUST reject that external input with `task_plan_input_reference_unavailable`
- **AND** the valid task reference MUST NOT relax validation of any sibling input

#### Scenario: Equivalent task URI forms
- **WHEN** inputs use `task:producer/output` and `task://producer/output`
- **THEN** validator, patch validator, and scheduler MUST resolve both to producer `producer`
- **AND** each consumer MUST declare `producer` in `depends_on`

#### Scenario: Task input points to unknown producer
- **WHEN** an explicit task input URI names a producer absent from the current Plan
- **THEN** validation MUST fail with `task_plan_unknown_dependency`
- **AND** the URI MUST NOT be treated as an external stage-context reference

#### Scenario: External input is not available in stage context
- **WHEN** an external input is policy-allowed but absent from current stage context
- **THEN** validation MUST fail with `task_plan_input_reference_unavailable`
- **AND** no task using that input may become ready

### Requirement: TaskPlan DAG analysis is deterministic and bounded
Initial candidate validation, patch validation, and ready ordering SHALL use the same dependency-depth semantics. DAG analysis MUST cache the actual depth for every visited task, MUST be independent of traversal order, MUST run in O(V+E), and MUST reject cycles, self-loops, unknown dependencies, unreachable tasks, and depth beyond the pinned policy.

#### Scenario: Dependency chain exceeds policy depth
- **WHEN** tasks form `A -> B -> C` and `max_depth` is 1
- **THEN** initial candidate validation and patch validation MUST fail with `task_plan_depth_exceeded`
- **AND** task ordering or prior visits to shared dependencies MUST NOT change the outcome

#### Scenario: Shared dependency is visited repeatedly
- **WHEN** multiple tasks depend on a previously analyzed producer
- **THEN** DAG analysis MUST reuse the producer's recorded depth
- **AND** every consumer depth MUST equal one plus the maximum dependency depth

### Requirement: TaskPlan replay entry points preserve patch evidence
`TaskPlanReplayReducer.reduce`, `TaskPlanReplayReducer.replay`, and `TaskPlanRecoveryService` SHALL consume equivalent Plan, patch, result, event, and terminal-event evidence. For the same evidence they MUST produce the same current Plan version and projection checksum without invoking live planners, workers, queues, tools, memory, or current policy defaults.

#### Scenario: Reduce replays accepted patch history
- **WHEN** history contains `PLAN_PATCH_ACCEPTED`, its patch document, the following accepted Plan version, and accepted task results
- **THEN** `reduce` and `replay` MUST produce the same Plan version, task projection, and projection checksum
- **AND** recovery MUST produce the same replay report without a live worker call

#### Scenario: Accepted patch document is missing
- **WHEN** replay observes `PLAN_PATCH_ACCEPTED` without its checksum-bound patch document
- **THEN** replay MUST fail with `task_plan_replay_patch_missing`
- **AND** it MUST NOT infer operations from the following Plan

#### Scenario: Patch evidence does not match accepted Plan
- **WHEN** patch base version, checksum, or next Plan evidence is inconsistent
- **THEN** replay MUST fail with `task_plan_replay_patch_mismatch`
- **AND** it MUST leave recorded evidence unchanged

### Requirement: TaskPlan integrity diagnostics are stable and bounded
TaskPlan integrity failures SHALL expose stable machine-readable reason codes and bounded safe details. Diagnostics MUST NOT contain raw prompts, secrets, tenant-private payloads, or complete worker outputs, and metrics MUST use only low-cardinality labels such as stage id, reason code, policy ref, and plan version.

#### Scenario: Integrity failure is inspected
- **WHEN** policy, input, DAG, halt persistence, or replay validation fails
- **THEN** inspection MUST expose the stable reason code and only checksum/reference/task/version evidence needed for repair
- **AND** raw candidate and worker payloads MUST remain redacted
