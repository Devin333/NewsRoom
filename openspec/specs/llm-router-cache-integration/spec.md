# llm-router-cache-integration Specification

## Purpose
TBD - created by archiving change llm-cache-production-hardening. Update Purpose after archive.
## Requirements
### Requirement: Router performs cache lookup before provider admission
For each deployment candidate, `LLMRouter` SHALL validate deployment enabled state and required capabilities, then evaluate cache eligibility and exact lookup before cooldown and provider/global budget admission. It SHALL perform cooldown, provider budget, provider invocation, route budget, and provider settlement only after a miss or bypass proceeds to the provider path.

#### Scenario: Cache hit while deployment is in cooldown
- **WHEN** an enabled capability-compatible primary deployment has a valid exact entry and is currently in cooldown
- **THEN** the router returns the cached response without evaluating cooldown as a rejection, calling a fallback, or invoking a provider

#### Scenario: Disabled deployment cannot serve cache
- **WHEN** a deployment is disabled even though a matching entry exists
- **THEN** the router applies the existing disabled-deployment behavior and does not consume the entry

#### Scenario: Capability mismatch cannot serve cache
- **WHEN** a deployment lacks a capability required by the route
- **THEN** the router applies the existing capability error behavior before lookup

#### Scenario: Miss preserves provider gate order
- **WHEN** lookup misses or caching is bypassed
- **THEN** cooldown, global provider-budget preflight, provider call, route validation/budget, settlement, and fallback remain in their established deterministic order

### Requirement: Cache hits do not mutate provider state
A valid cache hit SHALL NOT call a provider, reserve or settle provider token/cost budget, increment provider `llm_calls`, or update provider cooldown success/failure. It SHALL count one logical LLM request and preserve Harness verification and durable transcript behavior after the response returns.

#### Scenario: Hit avoids global provider budget
- **WHEN** a valid cache hit occurs while the provider call budget is exhausted
- **THEN** the hit succeeds without running provider-budget preflight and provider usage remains unchanged

#### Scenario: Hit leaves cooldown unchanged
- **WHEN** a cached response is returned
- **THEN** the deployment cooldown tracker receives no success or failure update

#### Scenario: Hit is still a logical request
- **WHEN** a cached response is returned
- **THEN** logical request accounting and current-call router evidence increase once while physical provider call/token/cost accounting remains zero

### Requirement: Responses carry unambiguous current-call cache metadata
The router SHALL decorate every returned response with current-call cache metadata including cacheable status, hit status, source, stable reason, key version, age when applicable, backend, provider-call status, and logical/provider budget-counting flags. Cached metadata from a previous call MUST NOT be reused as current routing evidence.

#### Scenario: Cached response is redecorated
- **WHEN** a valid entry contains source-result metadata from an earlier request
- **THEN** the router removes prior call IDs, run IDs, route events, fallback counters, and budget flags and emits fresh metadata for the current request

#### Scenario: Provider response reports a miss
- **WHEN** an eligible miss is fulfilled by a provider
- **THEN** response metadata identifies provider source, `llm_cache_hit=false`, and `llm_provider_call=true`

#### Scenario: Ineligible response reports bypass
- **WHEN** policy rejects caching
- **THEN** response metadata contains the stable bypass reason without claiming a lookup miss

### Requirement: Deployment identity isolates primary and fallback entries
Every lookup and write SHALL bind the exact `deployment_id`, provider, model, and cache generation. A response produced by one deployment MUST NOT be stored or replayed under another deployment's identity.

#### Scenario: Fallback success writes only fallback identity
- **WHEN** the primary misses and fails, then the fallback provider succeeds
- **THEN** only a fallback-deployment entry may be written

#### Scenario: Recovered primary does not consume fallback entry
- **WHEN** the primary becomes available after a fallback entry was written for the same logical request
- **THEN** the primary lookup misses unless a primary-specific entry exists

#### Scenario: Primary hit prevents fallback
- **WHEN** the primary has a valid entry even while its provider is unavailable or in cooldown
- **THEN** the router returns that entry and does not inspect the fallback provider path

### Requirement: Single-flight coordination is bounded and double-checked
On an eligible miss, the router SHALL attempt owner-token lease acquisition when single-flight is enabled. A non-owner SHALL wait only within the configured timeout and caller deadline, rechecking the exact entry. Only a current owner SHALL write a coordinated result. Timeout or coordinator failure SHALL fail open to the normal provider path without unbounded wait.

#### Scenario: Concurrent miss is collapsed
- **WHEN** concurrent routers miss the same key and one obtains the lease
- **THEN** the owner performs the provider call while waiters recheck and return the completed entry without provider calls

#### Scenario: Wait timeout is bounded
- **WHEN** no entry appears before the shorter of caller deadline and configured wait timeout
- **THEN** the waiter stops polling and follows the configured fail-open provider admission path

#### Scenario: Coordinator error does not authorize a write
- **WHEN** lease acquisition fails due to backend error
- **THEN** the request may continue to the provider, but it does not claim coordinated ownership and cannot overwrite an owner-protected result

### Requirement: Only fully accepted provider responses are cached
The router SHALL attempt a cache write only after a real provider response has passed current-request output-contract validation and all existing deterministic route/local/global gates required for success. Provider failures, schema failures, budget failures, and rejected responses MUST NOT populate the cache.

#### Scenario: Route budget rejects response
- **WHEN** a provider returns but the existing route budget guard rejects actual usage
- **THEN** no cache entry is written

#### Scenario: Output validation rejects response
- **WHEN** the provider response violates the current response format or output schema
- **THEN** the existing route/provider error contract applies and no cache write occurs

#### Scenario: Successful accepted response writes best-effort
- **WHEN** an eligible provider response passes all deterministic gates and mode permits writes
- **THEN** the router attempts one bounded write under the exact source deployment identity

### Requirement: Cache failures never mask provider outcomes
Runtime lookup, codec, coordinator, delete, or write failures SHALL be recorded and fail open without becoming provider successes or changing provider error taxonomy, retryability, fallback selection, cooldown mutation, or Harness halt/replan decisions.

#### Scenario: Lookup backend error followed by provider failure
- **WHEN** cache lookup fails and the provider then fails
- **THEN** the caller receives the existing provider/route failure, with cache failure preserved only as redacted diagnostic evidence

#### Scenario: Write error after successful provider call
- **WHEN** a valid provider response is returned but cache storage fails
- **THEN** the caller still receives the successful provider response and a write-failure event is recorded

#### Scenario: Corrupt entry is never treated as success
- **WHEN** lookup reports corruption
- **THEN** the router follows the miss path and cannot update cooldown as a cached success

### Requirement: Rollout modes have distinct side effects
The router SHALL implement `disabled`, `observe`, `write_only`, and `read_write` modes with deterministic behavior. Per-task allowlists SHALL apply in every non-disabled mode, and changing mode MUST NOT alter route resolution or Harness verification.

#### Scenario: Observe mode has no cache I/O
- **WHEN** mode is `observe`
- **THEN** eligibility and keyability evidence is emitted without backend read, write, lease, or provider-path suppression

#### Scenario: Write-only mode warms without serving
- **WHEN** mode is `write_only`
- **THEN** eligible accepted provider responses may be stored, but existing entries are not read or returned

#### Scenario: Read-write mode serves exact hits
- **WHEN** mode is `read_write` and an eligible valid exact entry exists
- **THEN** it is returned according to cache-hit accounting

#### Scenario: Disabled mode preserves baseline
- **WHEN** mode changes from `read_write` to `disabled`
- **THEN** no cache backend operation occurs and provider routing behaves as it did without cache integration

### Requirement: Router emits redacted durable cache evidence
The router SHALL reuse `LLMRouterEventSink` to emit stable lifecycle events for eligibility, lookup, hit, miss, single-flight wait, bypass, corruption, backend error, and write result. Events MUST include route/deployment identity, mode, version, reason, provider-call status, and bounded timing/size information, and MUST exclude prompts, responses, tool arguments, raw scope identifiers, secrets, and full keys.

#### Scenario: Hit evidence is complete and redacted
- **WHEN** a cache hit is served
- **THEN** eligibility/lookup/hit evidence identifies the current route and deployment with `provider_call=false` and contains no sensitive request or response material

#### Scenario: Backend failure evidence preserves cause class
- **WHEN** a cache operation fails
- **THEN** a stable bounded error class and operation are recorded without traceback, secret, Redis URL, raw key, or payload

#### Scenario: Cache evidence does not decide workflow quality
- **WHEN** a Harness run consumes a cached response
- **THEN** normal deterministic VERIFY and publication gates still execute and no cache event asserts quality pass/fail

### Requirement: Cache composition respects dependency direction
Production composition SHALL instantiate typed cache settings and infrastructure adapters outside `framework`, then inject only framework-owned ports into `LLMRouter`. Provider clients, endpoints, business workers, and LLM-generated tools MUST NOT construct or directly control production cache storage.

#### Scenario: Framework import boundary
- **WHEN** framework cache and router modules are imported
- **THEN** they have no dependency on Redis clients or infrastructure modules

#### Scenario: Disabled composition creates no Redis connection
- **WHEN** cache mode is `disabled`
- **THEN** composition does not resolve cache secrets or create a Redis client

#### Scenario: Test composition replaces the backend
- **WHEN** tests inject an in-memory or fake store/coordinator
- **THEN** the same router orchestration runs without infrastructure imports or global singletons

### Requirement: Client-owned production caching is removed
The production runtime SHALL NOT rely on `CachedLLMClient` or another provider-client wrapper to decide cache hits, budget flags, fallback identity, or Redis lifecycle. The bounded memory adapter MAY remain for explicit test/development injection through router-owned ports.

#### Scenario: Production deployment uses an unwrapped provider client
- **WHEN** production composition builds model deployments with cache enabled
- **THEN** clients remain ordinary `LLMClient` providers and cache orchestration is supplied to the router separately

#### Scenario: No duplicate client and router cache layers
- **WHEN** a request flows through a cache-enabled production router
- **THEN** exactly one router-owned cache lifecycle is executed
