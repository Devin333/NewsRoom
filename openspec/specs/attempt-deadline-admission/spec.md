# attempt-deadline-admission Specification

## Purpose
Define bounded, scope-aware retry and deadline admission across Graph activities, Tools,
parallel, and Worker execution without conflating local attempts, root retry
credits, live capacity, or resource ownership.
## Requirements
### Requirement: Root retry credits and local retry budgets are independent

The runtime SHALL create one `LocalRetryBudget` for each stable logical operation and one root-scoped `RetryCreditLedger` for the execution. `max_attempts` SHALL cap only that operation's local physical attempts; `max_total_retries` SHALL cap only admitted retry starts across the root execution. A first physical attempt SHALL consume no retry credit, and every admitted attempt with `local_attempt_no > 1` SHALL consume exactly one credit.

#### Scenario: Tool retry does not increment its parent Graph activity

- **WHEN** a Graph activity attempt 1 invokes a Tool whose own local attempt advances from 1 to 2
- **THEN** the Tool local attempt number becomes 2, the parent activity local attempt remains 1, the Tool reuses its logical idempotency key, and exactly one root retry credit is consumed

#### Scenario: Root retry ceiling blocks otherwise available local retries

- **WHEN** one logical operation consumes the last root retry credit while another operation still has an unused local retry slot
- **THEN** the second operation is rejected before start with `attempt_global_retry_exhausted`, and neither its local attempt counter nor the root credit counter changes

### Requirement: Physical attempt identity is separate from resource ownership

Every started physical attempt SHALL have a unique `attempt_id`, a stable `operation_id` and `idempotency_key`, a local `local_attempt_no`, an optional `parent_attempt_id`, and an optional opaque `retry_credit_id`. Generic attempt context SHALL NOT create, inherit, or expose a `fencing_token`; resource-specific leases SHALL be issued and validated only by their protected resource.

#### Scenario: Sibling operations have independent numbering and keys

- **WHEN** two sibling Tool calls start under one parent attempt
- **THEN** each receives a distinct operation key, distinct attempt ID, and local attempt number 1, and neither receives a parent-derived resource fence

#### Scenario: Resource lease remains resource-owned

- **WHEN** a Graph activity requests a node-output write lease after successful admission
- **THEN** the lease contains the resource-issued generation and owner attempt ID, and a budget sequence, Graph event sequence or retry credit cannot be used as that generation

### Requirement: Deadline admission rejects impossible work before side effects
The shared supervisor or equivalent admission controller SHALL compute child effective deadlines with a monotonic clock, treat the parent `AttemptContext.deadline` as an already-narrowed callable deadline, subtract only the child's cancellation and completion reserves, and require the resulting execution window to be at least `min_start_window_seconds`. Deterministic deadline/cancellation/budget gates SHALL complete before thread creation, executor or transport invocation, capacity acquisition, artifact preparation, or resource lease issuance. Capacity and budget reservations SHALL complete before the durable start fact and remain rollback-capable until that fact succeeds.

#### Scenario: Insufficient remaining window is rejected before start
- **WHEN** a child has 2 seconds of parent available time, a 5-second timeout, a 3-second minimum start window, and a 0.3-second cancellation/commit reserve
- **THEN** admission returns `attempt_deadline_admission_rejected`, the callable and transport are not invoked, and local budget, root credit, live capacity, write lease, and publication counts remain zero

#### Scenario: Adequate window is narrowed to the parent
- **WHEN** a child requests a 5-second timeout while the parent available deadline permits only 2 seconds after required reserves and the minimum window is 1 second
- **THEN** admission succeeds with an effective deadline no later than the parent available deadline and reports the deterministic calculation used

### Requirement: Root hard deadline includes cancellation, VERIFY, and commit reserves
The runtime SHALL keep cancellation grace, deterministic VERIFY, durable outcome recording, and final commit reserves within the root hard deadline. A child SHALL NOT extend or rebase the root deadline, and a cancelled parent SHALL reject new child admission while signalling cooperative cancellation to already running descendants.

#### Scenario: Nested deadline never expands
- **WHEN** a fake monotonic clock evaluates multiple nested operations with different local timeouts
- **THEN** every child effective deadline is no later than its parent's available deadline and no normal success or commit timestamp exceeds the root hard deadline

#### Scenario: Parent cancellation blocks a new child
- **WHEN** the parent cancellation signal is set before a child admission request
- **THEN** admission returns `attempt_parent_cancelled_before_start` without creating an attempt context, consuming budget, acquiring capacity, or issuing a lease

### Requirement: Typed deadline and retry policy validation fails closed
Timeout and execution policies SHALL expose typed non-negative `min_start_window_seconds`, `cancellation_grace_seconds`, `verify_reserve_seconds`, `commit_reserve_seconds`, and explicit `max_total_retries`. `min_start_window_seconds` SHALL NOT exceed an explicit timeout. Non-numeric, negative, NaN, infinity, contradictory, or hard-deadline-infeasible values SHALL be rejected before runtime side effects, and serialization round-trips SHALL preserve validated values.

#### Scenario: Invalid policy has no runtime side effect
- **WHEN** a policy contains a negative reserve, NaN window, or minimum window greater than its timeout
- **THEN** validation fails with a typed configuration error before any event other than the validation diagnostic, callable, capacity, budget, lease, or publication is created

#### Scenario: Typed policy round-trips
- **WHEN** a valid deadline/retry policy is serialized and deserialized
- **THEN** all typed fields and values, including zero reserves and the root retry ceiling, are preserved exactly

### Requirement: Admission reservation is atomic and has no ghost consumption
Admission SHALL serialize or transactionally reserve local attempt numbers, root retry credits, and live capacity so concurrent requests cannot duplicate local numbers or exceed ceilings. Capacity rejection SHALL not consume budget; budget rejection SHALL not consume capacity; thread creation or durable-start persistence failure SHALL release capacity and roll back uncommitted reservations. Resource preparation SHALL occur only after `attempt_started`; a preparation failure SHALL consume the started attempt and emit a terminal failure rather than being rewritten as a no-start rejection. Every successfully prepared attempt SHALL finalize caller-owned outcomes and execute resource cleanup exactly once before `attempt_terminal`; an unconfirmed finalization or cleanup SHALL emit `INDETERMINATE` rather than success.

#### Scenario: Concurrent local admission is unique and bounded
- **WHEN** concurrent requests for one logical operation race at a barrier with `max_attempts=2`
- **THEN** at most two physical starts are admitted, local attempt numbers are unique and ordered, and every rejected request leaves counters and capacity unchanged

#### Scenario: Capacity rejection is side-effect free
- **WHEN** all live execution slots are occupied before a retry admission
- **THEN** the result is `attempt_capacity_exhausted`, no attempt thread or resource lease is created, and local/root retry counters remain unchanged

#### Scenario: Resource cleanup precedes the terminal fact
- **WHEN** a started attempt succeeds, fails, or times out after resource preparation
- **THEN** its caller-specific finalizer and cleanup each run at most once before `attempt_terminal`, and cleanup failure changes the terminal state to `INDETERMINATE`

### Requirement: All runtime layers use one operation scope and admission order

Graph activities, parallel branches, Tool calls and batches, nested workers, and standalone timeout helpers SHALL create explicit logical operation contexts and route physical starts through the shared admission contract. Sibling operations SHALL not share local attempt numbers or idempotency keys; Graph node-output, queue, and storage lease ownership SHALL remain outside execution retry identity.

#### Scenario: Cross-layer scope matrix is isolated

- **WHEN** a test exercises a direct Tool, Graph Tool activity, ToolBatch child, parallel branch, nested worker Tool, and standalone timeout helper
- **THEN** each logical operation has its own local budget and stable key, retries only its own scope, and all starts obey the same deadline/capacity/credit order

#### Scenario: Node-output lease is acquired after activity admission

- **WHEN** a Graph activity request is rejected for deadline or capacity before start
- **THEN** no node-output lease is issued and the current valid owner remains unchanged

### Requirement: Retry safety and determinacy take precedence over remaining budget

The runtime SHALL preserve read-only, idempotent-write, reconciliation, and no-effect error contracts. `INDETERMINATE`, unconfirmed termination, unsafe external-write failure, and an indeterminate descendant SHALL block retry and normal commit/publication even when local and root budgets remain. A composite activity with a conservative external-write capability MAY preserve `FAILED` only when its trusted child outcomes explicitly confirm both termination and effect determinacy; absence of that proof SHALL remain fail-closed.

#### Scenario: Unsafe external write is terminal with budget remaining

- **WHEN** an external-write operation fails without idempotency and reconciliation support while both local and root retry budgets have capacity
- **THEN** it runs once, returns `INDETERMINATE`, and no retry admission is attempted

#### Scenario: Indeterminate descendant blocks publication

- **WHEN** a Tool or parallel branch remains unconfirmed after cancellation grace
- **THEN** the parent becomes indeterminate and commits no normal node output or artifact output regardless of remaining retry credits

#### Scenario: Read-only composite child failure remains determinate

- **WHEN** a ToolBatch activity has a conservative external-write capability but every failed child is read-only, terminated, and explicitly reports a determinate effect
- **THEN** the activity terminal remains `FAILED` rather than being upgraded to `INDETERMINATE`

### Requirement: Admission and execution outcomes are stable and scope-aware
The runtime SHALL emit separate durable admission and execution outcomes with stable reason codes, redacted policy/deadline calculations, local/root budget snapshots, operation identity, and determinacy/termination fields. Admission rejection events SHALL omit `attempt_id` and `local_attempt_no`; started attempt events SHALL include them. New live events SHALL NOT emit generic attempt `fencing_token` fields.

`AttemptSupervisor` SHALL be the sole publisher of the three generic lifecycle facts. A lifecycle sink explicitly attached to an outer operation SHALL be inherited by nested Tool, MCP, ToolBatch, parallel branch, and Worker operations without duplicate delivery to the same sink object. Durable sinks SHALL be required and fail closed; explicitly soft Tool/telemetry sinks SHALL be failure-isolated. A required started-sink partial failure SHALL close any previously recorded start with a terminal failure before the unopened callable is discarded.

#### Scenario: Rejection event distinguishes no-start from timeout
- **WHEN** deadline, local budget, root credit, capacity, or parent cancellation rejects a request
- **THEN** the event uses the corresponding `attempt_*` reason code, records `started=false` and no attempt identity, and does not classify the result as a post-start timeout

#### Scenario: Started outcome carries determinacy
- **WHEN** a physical attempt succeeds, fails, confirms timeout termination, or remains unconfirmed
- **THEN** its outcome records `attempt_id`, local attempt number, stable operation key, termination confirmation, and `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `INDETERMINATE` state consistently

#### Scenario: Soft telemetry cannot gate execution
- **WHEN** a Tool event mirror or Worker telemetry sink fails while a required durable sink remains available
- **THEN** the callable and required lifecycle continue, while the soft sink failure changes neither admission nor the terminal result

### Requirement: Legacy attempt history is read-only replayable and new history is unambiguous
The runtime SHALL provide a versioned read-only decoder for legacy shared-budget and `fencing_token` event/error fields. Legacy `max_total_attempts` SHALL NOT be silently mapped to `max_total_retries`; migration or compilation SHALL explicitly produce the new policy. Offline replay SHALL not invoke workers, Tools, transports, leases, or external effects, and new live history SHALL use scope-aware identity without generic attempt fences.

#### Scenario: Legacy replay has no live side effect
- **WHEN** an old history containing shared permit and fencing fields is replayed
- **THEN** the decoder exposes legacy fields for diagnostics only, replay produces the same projection without starting live work, and no new resource lease is accepted from the old value

#### Scenario: New history contains no generic fence
- **WHEN** a new execution emits admission and attempt events
- **THEN** the serialized records contain local/root budget and resource-specific lease fields where applicable but no generic attempt `fencing_token` field
