## MODIFIED Requirements

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
