## ADDED Requirements

### Requirement: Canonical cumulative LLM budget owner
`framework/governance/budget` SHALL be the only production owner of mutable cumulative LLM call, input-token, output-token, reasoning-token, cached-input-token, and estimated-cost accounting. Its public contract MUST NOT contain retry, deadline, tool-call, wall-time, context-capacity, loop, stall, quality, publication, authorization, or diagnostics dimensions.

#### Scenario: Architecture dependency and dimension audit
- **WHEN** production modules and canonical budget exports are inspected
- **THEN** Agent and Workflow modules contain no independent cumulative LLM ledger implementation
- **AND** the canonical package imports no Agent, Workflow, Business, Interfaces, or Infrastructure module

### Requirement: Strict policy and amount values
Canonical amount values SHALL expose exactly the six declared dimensions. Canonical policy SHALL expose a schema version, policy revision, bounded non-negative per-dimension limits, and MAY expose a derived total-token constraint over input, output, and reasoning tokens without creating another usage dimension. Counts and tokens MUST reject booleans, negatives, non-integers, and overflow; cost MUST reject booleans, negatives, NaN, Infinity, overflow, and non-canonical durable representations.

#### Scenario: Invalid external amount fails closed
- **WHEN** a caller supplies an unknown dimension, negative count, boolean token value, non-finite cost, or value above the supported bound
- **THEN** validation raises a typed contract error
- **AND** no ledger usage, reservation, revision, or event is changed

#### Scenario: Cost is stable across serialization
- **WHEN** a valid decimal cost is serialized, restored, and serialized again
- **THEN** both durable payloads contain the same canonical decimal string
- **AND** no binary floating-point drift is introduced

### Requirement: Explicit scope tree and inherited ceiling
Every ledger SHALL have one run root scope and MAY register workflow, agent-loop, subagent, and operation child scopes. A child MUST reference an existing parent in the same run and MAY only narrow a finite ancestor limit. Every reservation and settlement SHALL project to its scope and all ancestors, so no child configuration or `inherit_budget=False` behavior can bypass the root ceiling.

#### Scenario: Child cannot widen root limit
- **WHEN** a child policy omits a finite root limit or declares a larger local limit
- **THEN** its effective limit remains no greater than the ancestor limit

#### Scenario: Siblings compete for the same final slot
- **WHEN** sibling scopes concurrently reserve the last available root call, token, or cost capacity
- **THEN** only the number permitted by the root ceiling is admitted
- **AND** all denied decisions are deterministic and leave totals within the ceiling

### Requirement: Atomic admission and idempotent reservation
`reserve` SHALL perform identity lookup, current usage read, ancestor limit checks, reservation creation, usage mutation, revision increment, and event preparation as one linearized operation. Repeating the same operation and idempotency identity with identical scope, policy, and amounts SHALL return the original reservation; conflicting reuse SHALL fail closed without mutation.

#### Scenario: Concurrent limit plus one admission
- **WHEN** `limit + 1` callers reserve concurrently against a limit-sized root budget
- **THEN** exactly `limit` reservations succeed
- **AND** committed plus reserved usage never exceeds the root ceiling

#### Scenario: Repeated reserve delivery
- **WHEN** the same reserve command is delivered twice with identical content
- **THEN** both deliveries identify the same reservation and ledger revision
- **AND** usage increases only once

### Requirement: Read-only deterministic decisions and views
Preflight, denial, and views SHALL expose immutable committed, reserved, available, projected usage, sorted stable reason codes, and revision without exposing mutable ledger state. A decision MUST NOT select or execute provider, fallback, retry, replan, approval, quality, publication, memory-write, or workflow routes.

#### Scenario: Denied operation cannot authorize a route
- **WHEN** a request exceeds one or more effective limits
- **THEN** the ledger returns a denied decision with sorted stable violations
- **AND** the decision contains no executable route or side-effect authority
