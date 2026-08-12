## ADDED Requirements

### Requirement: One identity per logical operation and dispatch attempt
Every logical LLM operation SHALL have a stable operation identity and at most one active reservation. Each real fallback provider dispatch SHALL use a distinct child attempt identity correlated to the logical parent. Router, AgentLoop, Workflow, cache, and stream adapters MUST pass the same identity rather than independently recording the same operation.

#### Scenario: Router and AgentLoop share one settlement
- **WHEN** AgentLoop receives a router response carrying a canonical terminal settlement
- **THEN** AgentLoop consumes the canonical view and does not record another call, token, or cost delta

#### Scenario: Fallback dispatches are distinct
- **WHEN** a primary dispatch fails and a fallback is dispatched
- **THEN** each physical dispatch has one distinct reservation and terminal fact under the same logical parent
- **AND** neither attempt is counted twice by an upper layer

### Requirement: Exactly-once normalized settlement
Settlement SHALL validate reservation, operation, scope, policy digest, state, and normalized actual usage. It SHALL replace reserved input with actual input and commit output, reasoning, cached input, logical call, and canonical cost exactly once. An exact repeated terminal delivery SHALL return the stored settlement without changing usage or revision; a conflicting delivery SHALL fail closed.

#### Scenario: Duplicate terminal event is idempotent
- **WHEN** the same successful settlement is delivered more than once
- **THEN** every delivery returns the original terminal settlement
- **AND** committed usage and ledger revision equal the values after the first delivery

#### Scenario: Actual input replaces estimate
- **WHEN** an operation reserves estimated input and settles with different normalized actual input within its ceiling
- **THEN** committed input equals the actual input
- **AND** the estimate is not added to committed usage

### Requirement: Dispatch-aware release and indeterminate outcome
Only an operation proven not dispatched and not consumed MAY release its reservation. A dispatched or uncertain operation without reliable actual usage MUST become indeterminate and retain its reserved capacity until deterministic reconciliation. Known usage above the admitted reservation MUST also become indeterminate rather than silently overrun or refund the ceiling.

#### Scenario: Transport failure before dispatch releases
- **WHEN** an adapter proves the provider or cache operation was not dispatched
- **THEN** release removes the reservation without committed usage

#### Scenario: Accepted request loses response
- **WHEN** provider dispatch is confirmed but its terminal usage cannot be established
- **THEN** the operation becomes indeterminate
- **AND** its capacity is not returned for another dispatch

### Requirement: Cache fallback stream and failure conformance
LLM adapters SHALL translate structured cache, dispatch, fallback, stream-terminal, and provider-failure metadata into the same lifecycle semantics. A cache hit SHALL count one admitted logical call with zero provider dispatch and zero provider cost; stream fragments SHALL not settle; a stream SHALL settle only at its terminal fact; terminal loss SHALL be indeterminate.

#### Scenario: Cache hit uses logical accounting only
- **WHEN** a valid exact cache hit is returned
- **THEN** one canonical logical operation is admitted and settled
- **AND** provider dispatch and provider cost remain zero

#### Scenario: Stream fragments do not double count
- **WHEN** a stream produces multiple fragments followed by one terminal usage event
- **THEN** fragments do not mutate committed usage
- **AND** the terminal event settles the operation exactly once

### Requirement: Domain-specific budgets retain their owners
The LLM adapter SHALL retain per-call token/cost policy, pricing, provider normalization, and context-preflight integration. Workflow SHALL retain tool-call and wall-time budgets; Agent SHALL retain loop, parser, judge, output, retry, and stall limits; shared attempts and Harness SHALL retain retry credits and deadlines. These owners MAY consume canonical views but MUST NOT write independent cumulative LLM totals.

#### Scenario: Workflow summary combines without merging owners
- **WHEN** Workflow renders a budget summary
- **THEN** LLM cumulative values come from a canonical read-only view
- **AND** tool calls and wall time come from Workflow-owned state

### Requirement: Compatibility facades delegate to canonical state
Legacy `GlobalBudget*` imports MAY remain for one release only as explicit aliases, value mappers, or stateless facades over one canonical ledger. A facade MUST NOT own a second usage object, admission algorithm, event format, or private-field restore path, and new production code MUST NOT import cumulative types from Agent or Workflow compatibility modules.

#### Scenario: Legacy facade and canonical view agree
- **WHEN** a supported legacy call records usage through the facade
- **THEN** the facade snapshot is a projection of the canonical ledger
- **AND** no second mutable cumulative usage exists
