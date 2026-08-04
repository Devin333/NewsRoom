## ADDED Requirements

### Requirement: Timed attempts receive cooperative cancellation and termination confirmation
The Tool and Workflow runtimes SHALL execute bounded callables under an attempt context containing a unique attempt id, deadline, cancellation signal, stable logical-operation idempotency key, and fencing generation. On deadline the runtime SHALL signal cancellation and SHALL distinguish confirmed termination from an attempt that may still be running.

#### Scenario: Cooperative attempt reaches its deadline
- **WHEN** an attempt exceeds its deadline and exits within the configured cancellation grace interval
- **THEN** the runtime records a timeout with confirmed termination
- **AND** no later work from that attempt is accepted

#### Scenario: Attempt ignores cancellation
- **WHEN** an attempt remains alive after the cancellation grace interval
- **THEN** the runtime returns a typed indeterminate or unconfirmed-timeout result
- **AND** does not represent `Future.cancel()` or a timed join as successful termination

### Requirement: Timeout retry never overlaps an uncertain attempt
The runtime SHALL NOT start a retry while the previous attempt may still be running. After confirmed termination, timeout retry SHALL be allowed only for read-only work or work with an explicit stable idempotency contract and remaining shared retry budget.

#### Scenario: Non-cooperative attempt times out
- **WHEN** a Tool or Workflow attempt remains active after cancellation grace
- **THEN** automatic retry is halted even when the ordinary retry policy has attempts remaining
- **AND** the result identifies the outcome as indeterminate without exposing exception contents

#### Scenario: Read-only attempt terminates after cancellation
- **WHEN** a read-only attempt times out, confirms termination, and its retry policy allows another attempt
- **THEN** the next attempt starts only after that confirmation
- **AND** it receives a new attempt id and the same logical idempotency key

#### Scenario: External write has uncertain completion
- **WHEN** an external or irreversible operation crosses its deadline
- **THEN** the runtime does not automatically repeat the operation without a verified idempotency and reconciliation contract

### Requirement: Workflow attempt writes are fenced and staged
Each Workflow step attempt SHALL use a private buffer overlay, and only the current successfully completed fencing generation SHALL atomically publish staged writes, deletes, lineage, and schema-valid values to the base `DataBuffer`.

#### Scenario: Timed-out attempt writes after the caller returns
- **WHEN** a timed-out step thread later tries to write through its attempt buffer
- **THEN** the write is rejected as stale
- **AND** the base buffer, write history, lineage, and snapshot version remain unchanged

#### Scenario: Successful current attempt commits
- **WHEN** the current fenced attempt returns a successful outcome
- **THEN** its staged mutations are validated and committed as one attempt publication
- **AND** readers observe no partial staged state before commit

#### Scenario: Retry succeeds after a terminated prior attempt
- **WHEN** a retryable safe attempt confirms termination and a later attempt succeeds
- **THEN** only the later successful attempt's overlay is committed

### Requirement: Timeout status remains explicit across Tool and Workflow layers
The system SHALL preserve timeout and indeterminate-timeout status across Tool results, Tool-backed Workflow steps, events, and retry decisions instead of converting them to generic failure.

#### Scenario: Tool-backed step times out
- **WHEN** `ToolExecutor` returns a Tool timeout result
- **THEN** `ToolCallStepRunner` returns `StepStatus.TIMEOUT`
- **AND** Step retry policy receives the timeout type and termination metadata

#### Scenario: Tool and step retry policies are both configured
- **WHEN** a Tool-backed step has retry policy at both layers
- **THEN** the execution uses one shared total-attempt budget
- **AND** an unconfirmed attempt consumes the terminal budget position without starting another attempt
