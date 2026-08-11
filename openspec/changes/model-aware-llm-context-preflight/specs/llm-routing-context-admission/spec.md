## ADDED Requirements

### Requirement: Router requires a usable context profile before provider admission
`LLMRouter` SHALL resolve and validate a deployment-bound context profile before cache, cooldown, global-budget, or provider admission. A deployment with no usable profile SHALL fail closed for router-managed provider calls unless an explicit conservative fallback profile was injected by trusted composition.

#### Scenario: Deployment has no profile
- **WHEN** a router-managed deployment lacks a valid profile and no trusted fallback profile is configured
- **THEN** the router records `PROFILE_REQUIRED`, performs no provider call, and returns a non-retryable route failure if no eligible fallback exists

#### Scenario: Request metadata supplies a fake profile
- **WHEN** deployment profile is absent but request metadata contains profile-like values
- **THEN** the router ignores those values and still fails closed

### Requirement: Each deployment is prepared before physical admission
For every enabled, functionally compatible deployment considered by a route, the router SHALL prepare and admit the request against that deployment before any provider call or provider-budget reservation. The client SHALL receive the normalized request from the admitted prepared object, not the unprepared logical request.

#### Scenario: Primary request is admitted
- **WHEN** the primary deployment is enabled, capability-compatible, and its prepared request is admitted
- **THEN** exactly that normalized request is passed to the primary client

#### Scenario: Primary input is too large
- **WHEN** primary preflight returns `INPUT_LIMIT_EXCEEDED`
- **THEN** the primary client call count, cooldown mutation count, and global provider-budget reservation count remain zero

#### Scenario: Primary output contract is unsupported
- **WHEN** primary preflight returns `OUTPUT_LIMIT_EXCEEDED`
- **THEN** the primary is not called and its request output is not silently reduced

### Requirement: Physical-capacity fallback is deterministic and policy bounded
When a configured primary deployment is rejected for a typed physical-capacity outcome, the router SHALL evaluate later configured deployments in route order. Every candidate MUST independently pass enabled, capability, profile, output, input, tenant/data-boundary, and existing route policy checks. Capacity fallback MUST NOT authorize an unconfigured model, semantic context mutation, or an expanded Harness budget.

#### Scenario: Larger fallback fits
- **WHEN** primary input capacity is insufficient and the next configured compatible deployment admits the request
- **THEN** the router selects the fallback before any primary provider call and records the primary admission reason

#### Scenario: All deployments are too small
- **WHEN** every configured compatible deployment rejects the input or output contract
- **THEN** no provider is called and the route fails with typed capacity evidence for every considered deployment

#### Scenario: Larger model lacks a required capability
- **WHEN** a fallback has sufficient context capacity but lacks a required functional capability
- **THEN** it is not selected and capacity alone does not override the capability gate

### Requirement: Complete and stream share the same preflight contract
Router `complete` and `stream` paths SHALL use the same profile resolution, normalizer, token counter, effective budget, admission rules, deployment ordering, fingerprint contract, and redacted preflight events. Streaming preflight MUST finish before the first provider stream item is requested.

#### Scenario: Complete and stream prepare the same request
- **WHEN** complete and stream are invoked with the same route, request, deployment registry, and revisions
- **THEN** their admitted prepared fingerprints, counts, budgets, and selected deployments are identical

#### Scenario: Streaming request is too large
- **WHEN** all stream-capable deployments reject preflight
- **THEN** the provider stream iterator is never opened and no stream event is yielded

#### Scenario: Stream has yielded visible output
- **WHEN** a provider stream fails after the router has yielded any user-visible event
- **THEN** the router does not switch deployments or splice a fallback response into that stream

### Requirement: Global budget uses admitted input tokens
The router SHALL reserve global LLM provider budget using `PreparedLLMRequest.token_count.total_input_tokens`. Rejected deployments MUST NOT reserve or settle provider budget, and the legacy rough estimate MUST NOT be used for router-managed budget admission.

#### Scenario: Admitted count is reserved
- **WHEN** a prepared request is admitted and a global budget tracker is configured
- **THEN** pre-call reservation uses the admitted total input count

#### Scenario: Capacity rejection has no budget side effect
- **WHEN** a deployment fails profile, output, counter, or input admission
- **THEN** no global provider-call or prompt-token reservation is recorded for that deployment

### Requirement: Router emits redacted prepared-request evidence
The router SHALL emit profile-resolved, request-prepared, admission-decided, and capacity-fallback events through `LLMRouterEventSink`. Successful response metadata and route manifests SHALL reference the admitted prepared-request projection. Evidence MUST include bounded identity, revisions, component counts, budget values, status/reason, fingerprint, and provider-call state, and MUST exclude prompt text, message content, tool arguments/schema bodies, output schema bodies, secrets, and raw provider payloads.

#### Scenario: Admission event is reviewable
- **WHEN** a deployment admission is decided
- **THEN** its event identifies route/deployment, profile and counter revisions, count breakdown, effective budget, admission status, and fingerprint without request content

#### Scenario: Failed route retains all capacity decisions
- **WHEN** no deployment admits the request
- **THEN** the route error manifest contains one bounded redacted admission projection per considered compatible deployment

### Requirement: Context preflight precedes cache identity without owning cache policy
Router preparation SHALL occur before any response-cache lookup so cache identity can consume the admitted payload fingerprint and deployment/profile/normalizer revisions. This capability MUST NOT decide cache eligibility, mode, TTL, storage, single-flight, replay, or write acceptance.

#### Scenario: Profile revision changes
- **WHEN** the same logical request is prepared after a deployment profile revision change
- **THEN** cache consumers receive a different versioned prepared identity and cannot silently reuse the earlier profile identity

#### Scenario: Cache is disabled
- **WHEN** no cache ports are configured
- **THEN** the same preparation, admission, budget, provider, event, and manifest behavior remains valid

### Requirement: Router physical preflight does not claim global callsite closure
This change SHALL enforce model-aware preflight for calls made through `LLMRouter` but MUST NOT report that all production LLM callsites are protected until the separate managed-callsite convergence change proves direct-client migration.

#### Scenario: Direct client remains in live tree
- **WHEN** production composition still injects an `LLMClient` directly into a worker
- **THEN** this change's evidence reports router enforcement only and does not claim repository-wide callsite closure
