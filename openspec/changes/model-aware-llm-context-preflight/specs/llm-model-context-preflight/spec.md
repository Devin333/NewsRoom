## ADDED Requirements

### Requirement: Model context profiles are immutable and deployment-bound
The system SHALL resolve an immutable, versioned `ModelContextProfile` for the selected deployment. The profile MUST contain a positive physical context window, positive maximum and default output limits, tokenizer and normalizer identities, an operational input fraction in `(0, 1]`, a non-negative safety margin, provider auto-truncation policy, and deployment/provider/model identity. A request or its metadata MUST NOT override the resolved profile.

#### Scenario: Valid profile is resolved
- **WHEN** a deployment has a complete valid context profile
- **THEN** preflight uses that exact profile and records its revision and deployment identity

#### Scenario: Request metadata attempts profile override
- **WHEN** request metadata contains context-window, output-limit, tokenizer, or profile values
- **THEN** those values do not alter the deployment-resolved profile or budget

#### Scenario: Invalid profile is rejected at composition
- **WHEN** a profile has a non-positive limit, an invalid fraction, an empty revision, or a default output larger than maximum output
- **THEN** configuration validation fails before provider runtime

### Requirement: Provider-semantic normalization is shared by counting and dispatch
The system SHALL normalize every token-affecting request field through a versioned provider-semantic normalizer before counting. The selected deployment model, messages, adapted tools, response format or output schema, requested output, and supported media descriptors MUST be represented consistently in the normalized payload used for counting, fingerprinting, and provider dispatch.

#### Scenario: Output schema has one provider representation
- **WHEN** an `LLMRequest` contains an output schema
- **THEN** preflight counts and fingerprints the same provider response-format representation that the provider client dispatches

#### Scenario: Tool schema is adapted before count
- **WHEN** an `LLMRequest` contains framework tool definitions
- **THEN** the token counter receives the provider-adapted tool payload rather than a message-only or raw-tool approximation

#### Scenario: Diagnostic metadata is excluded
- **WHEN** request metadata is not projected into provider payload by a typed normalizer rule
- **THEN** it does not affect token count or payload fingerprint

### Requirement: Token counting reports component method and revision
The system SHALL count normalized messages, tools, response schema/format, media, and protocol overhead and return a component-level `LLMTokenCount`. Every count MUST identify its method, tokenizer family, tokenizer revision, and normalizer revision. `total_input_tokens` MUST equal the sum of its components.

#### Scenario: Exact counter is registered
- **WHEN** a profile tokenizer family has a registered exact or provider counter
- **THEN** preflight uses it and identifies the exact/provider method and revision in the result

#### Scenario: Count breakdown is internally consistent
- **WHEN** a normalized request is counted
- **THEN** its total equals message, tool, response-schema, media, and protocol-overhead component counts

#### Scenario: Tool-only growth is visible
- **WHEN** two requests have identical messages but one has a large tool schema
- **THEN** the second request has a larger tool count and total input count

### Requirement: Conservative fallback is explicit and fail closed when unsafe
The system SHALL provide an injectable counter registry and MAY use the built-in canonical UTF-8-byte fallback only when the profile explicitly permits it for that tokenizer family. Fallback results MUST be labeled `conservative_fallback` and MUST NOT be described as exact. If no registered counter or permitted conservative fallback exists, preflight SHALL return `COUNTER_UNAVAILABLE` without provider I/O.

#### Scenario: Permitted fallback is used
- **WHEN** no exact counter is registered and the profile permits canonical UTF-8-byte fallback
- **THEN** preflight returns a conservative count with the fallback method and revision

#### Scenario: Unsafe fallback is disabled
- **WHEN** no counter is registered and the profile does not permit the fallback
- **THEN** admission is `COUNTER_UNAVAILABLE` and no provider request is authorized

### Requirement: Output reserve is resolved without silent clamping
The system SHALL resolve requested output from `LLMRequest.max_tokens` or the profile default and SHALL reserve that full amount before input admission. If requested output exceeds the deployment maximum, admission SHALL be `OUTPUT_LIMIT_EXCEEDED`; the request MUST NOT be silently clamped or dispatched under a smaller output contract.

#### Scenario: Explicit output fits model maximum
- **WHEN** request output is positive and no greater than model maximum
- **THEN** the effective budget reserves exactly the requested output

#### Scenario: Default output is used
- **WHEN** the request does not specify `max_tokens`
- **THEN** the effective budget reserves the versioned profile default

#### Scenario: Requested output exceeds model maximum
- **WHEN** request `max_tokens` is greater than profile maximum output
- **THEN** admission is `OUTPUT_LIMIT_EXCEEDED`, the original request remains unchanged, and no provider call is authorized

### Requirement: Effective context budget is deterministic
The system SHALL compute operational limit as `floor(physical_limit * operational_input_fraction)` and maximum input as `operational_limit - reserved_output - safety_margin`. Admission SHALL be `ADMITTED` only when maximum input is positive and counted input is less than or equal to it.

#### Scenario: Exact boundary fits
- **WHEN** counted input equals maximum input
- **THEN** admission is `ADMITTED`

#### Scenario: One token exceeds the boundary
- **WHEN** counted input is one token greater than maximum input
- **THEN** admission is `INPUT_LIMIT_EXCEEDED`

#### Scenario: Reserve consumes the operational window
- **WHEN** output reserve and safety margin leave no positive input budget
- **THEN** preflight rejects the profile/request combination without provider I/O

### Requirement: Prepared request identity is immutable and complete
The system SHALL produce an immutable `PreparedLLMRequest` containing the normalized request, normalized-payload SHA-256 fingerprint, deployment/profile/tokenizer/normalizer revisions, token count, effective budget, and typed admission. The fingerprint MUST cover all response-affecting provider payload fields and MUST exclude secrets and non-provider diagnostic metadata.

#### Scenario: Same semantic payload is stable
- **WHEN** the same request is prepared twice for the same deployment and revisions
- **THEN** both prepared requests have the same fingerprint, count, budget, and admission

#### Scenario: Tool or schema changes identity
- **WHEN** a tool definition, output schema, model, temperature, or output limit changes
- **THEN** the prepared fingerprint changes

#### Scenario: Metadata-only diagnostic change does not alter identity
- **WHEN** only excluded diagnostic metadata changes
- **THEN** the prepared fingerprint remains unchanged

### Requirement: Physical preflight never mutates semantic context
The preflight layer MUST NOT delete, truncate, summarize, reorder, or otherwise change messages, tools, evidence, schemas, or tool transactions to make a request fit. A rejected prepared request SHALL preserve the original semantic request and provide a typed reason for Harness-controlled fallback, compaction, replan, or halt.

#### Scenario: Oversized request is rejected unchanged
- **WHEN** normalized input exceeds the deployment maximum input budget
- **THEN** preflight returns `INPUT_LIMIT_EXCEEDED` without removing or rewriting any context content

#### Scenario: Legacy strategy requests truncation
- **WHEN** a legacy `ContextPolicy` names a truncate or summarize strategy
- **THEN** model-aware preflight does not execute that content mutation
