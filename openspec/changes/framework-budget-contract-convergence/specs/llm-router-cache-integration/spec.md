## MODIFIED Requirements

### Requirement: Router performs cache lookup before provider admission
For each deployment candidate, `LLMRouter` SHALL validate deployment enabled state and required capabilities, prepare the canonical logical budget operation, then evaluate cache eligibility and exact lookup before cooldown and physical provider admission. A valid hit SHALL settle the already-admitted logical operation with structured cache metadata and no provider dispatch or cost. The router SHALL perform cooldown, physical provider invocation, route budget, provider usage settlement, and fallback only after a miss or bypass proceeds to the provider path.

#### Scenario: Cache hit while deployment is in cooldown
- **WHEN** an enabled capability-compatible primary deployment has a valid exact entry and is currently in cooldown
- **THEN** the router returns the cached response without evaluating cooldown as a rejection, calling a fallback, or invoking a provider
- **AND** the canonical logical operation is settled exactly once

#### Scenario: Disabled deployment cannot serve cache
- **WHEN** a deployment is disabled even though a matching entry exists
- **THEN** the router applies the existing disabled-deployment behavior and does not consume the entry

#### Scenario: Capability mismatch cannot serve cache
- **WHEN** a deployment lacks a capability required by the route
- **THEN** the router applies the existing capability error behavior before lookup

#### Scenario: Miss preserves provider gate order
- **WHEN** lookup misses or caching is bypassed
- **THEN** cooldown, physical provider invocation, route validation/budget, canonical settlement, and fallback remain in their established deterministic order

### Requirement: Cache hits do not mutate provider state
A valid cache hit SHALL NOT call a provider, reserve or settle physical provider token/cost budget, increment physical provider-call accounting, or update provider cooldown success/failure. It SHALL admit and settle one canonical logical LLM operation, record zero provider cost, and preserve Harness verification and durable transcript behavior after the response returns.

#### Scenario: Hit avoids physical provider budget
- **WHEN** a valid cache hit occurs while physical provider-call capacity is unavailable but canonical logical-call capacity remains
- **THEN** the hit succeeds without a provider dispatch or provider-cost mutation
- **AND** one canonical logical operation is settled

#### Scenario: Logical budget can deny a hit
- **WHEN** a valid cache entry exists but the canonical root logical-call ceiling is exhausted
- **THEN** the hit is denied before returning cached content
- **AND** no provider or cache-success side effect bypasses the root ceiling

#### Scenario: Hit leaves cooldown unchanged
- **WHEN** a cached response is returned
- **THEN** the deployment cooldown tracker receives no success or failure update

#### Scenario: Hit is still a logical request
- **WHEN** a cached response is returned
- **THEN** canonical logical request accounting and current-call router evidence increase once while physical provider call and provider cost accounting remain zero
