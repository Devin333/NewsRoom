## ADDED Requirements

### Requirement: Provider context overflow has a stable non-transient type
Provider adapters SHALL normalize HTTP 413 and explicitly mapped structured provider context-window error codes to `LLMProviderContextOverflow`, with canonical category `context_length` and `retryable=false`. Adapters MUST NOT infer overflow by keyword-matching arbitrary provider error messages.

#### Scenario: HTTP 413 is returned
- **WHEN** a provider responds with HTTP 413
- **THEN** the client raises `LLMProviderContextOverflow` with `retryable=false`

#### Scenario: Structured overflow code is returned with HTTP 400
- **WHEN** a provider returns an explicitly mapped structured code such as `context_length_exceeded`
- **THEN** the client raises the same stable overflow type and retains only bounded mapped diagnostics

#### Scenario: Arbitrary invalid-request message mentions tokens
- **WHEN** an unmapped HTTP 400 message contains token or length words
- **THEN** it remains the normal invalid-request type and is not guessed to be context overflow

### Requirement: Provider client never retries context overflow internally
An `LLMProviderContextOverflow` MUST terminate the provider client's retry loop immediately regardless of configured transient retry attempts. It MUST NOT sleep, consume another same-deployment provider attempt, or update retryable-failure cooldown state.

#### Scenario: Overflow occurs on first provider attempt
- **WHEN** max provider attempts is greater than one and the first response is context overflow
- **THEN** exactly one provider attempt occurs, no retry delay executes, and the error remains non-retryable

### Requirement: Router records estimator drift without exposing provider bodies
When provider overflow contradicts an admitted prepared request, the router SHALL emit bounded drift evidence containing local component/total count, effective limits, profile/tokenizer/normalizer revisions, provider status/code, and explicitly mapped provider-reported token limit or usage when available. Prompt, tool/schema content, raw response body, and secrets MUST NOT be recorded.

#### Scenario: Provider reports a bounded token limit
- **WHEN** an admitted request receives context overflow with a mapped numeric limit
- **THEN** the overflow event records that limit and local preflight evidence without raw provider content

#### Scenario: Provider reports no usable counts
- **WHEN** overflow contains no mapped numeric usage or limit
- **THEN** drift evidence records those fields as unavailable rather than inventing values

### Requirement: Overflow recovery is cross-deployment and bounded
Before any user-visible output, the router MAY recover from provider context overflow by re-preparing the logical request for at most one later configured compatible deployment with a different usable profile. The router MUST NOT re-dispatch the identical prepared request to the same deployment, exceed the route/Harness retry or turn budget, or perform semantic context mutation in this change.

#### Scenario: Compatible fallback profile admits after overflow
- **WHEN** the primary reports context overflow before output and one later configured deployment independently admits the request
- **THEN** the router may call that fallback once and records overflow-driven capacity fallback

#### Scenario: Same deployment would be retried
- **WHEN** no different eligible deployment exists
- **THEN** the route fails without a second call to the same deployment

#### Scenario: More than one overflow fallback is available
- **WHEN** an overflow recovery attempt also overflows
- **THEN** no second overflow-driven recovery occurs and the route fails deterministically

### Requirement: Streaming overflow cannot splice providers
Streaming context overflow MAY select the one bounded fallback only if it occurs before the router yields a user-visible stream event. After any visible event, overflow SHALL terminate the stream under the existing error contract without starting a fallback provider.

#### Scenario: Overflow occurs while opening stream
- **WHEN** primary stream creation raises context overflow before any event is yielded
- **THEN** the router may re-prepare and open one eligible fallback stream

#### Scenario: Overflow occurs after a text delta
- **WHEN** primary stream has yielded visible output and then raises context overflow
- **THEN** the router propagates failure and does not open another deployment stream

### Requirement: Provider overflow does not authorize Harness decisions
Provider overflow and drift evidence SHALL be diagnostic physical-capacity signals only. They MUST NOT mark context compaction verified, change evidence quality, authorize tool or memory operations, or decide workflow routing, publication, retry, replan, or halt outside existing deterministic Harness policy.

#### Scenario: Harness consumes overflow evidence
- **WHEN** a Harness-controlled run receives a route failure caused by provider overflow
- **THEN** Harness applies its existing bounded policy and no provider or LLM output self-authorizes the next state
