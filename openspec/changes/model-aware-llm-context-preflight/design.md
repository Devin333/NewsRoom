## Context

The existing LLM context layer is an isolated MVP. `estimate_request_tokens()` serializes logical request fields and divides character count by four; `LLMContextGuard` compares that estimate with a caller-owned static limit; `LLMContextCompressor` drops old messages; and `LLMRouter` uses only the estimate for event metadata and global budget reservation before calling `deployment.client.complete(request)`.

The live model registry already exposes `ModelCapabilities.context_window_tokens` and `max_output_tokens`, but those fields do not participate in routing. Provider adapters independently transform tools and response schemas, so the current estimator does not count the exact semantic payload that is sent. The router also has no stream method, while the active cache-hardening change requires complete and stream to share route and identity semantics.

This change is the physical-preflight slice of stage 24. It does not decide which evidence, memory, conversation turns, or tool transactions may be removed. Those are semantic decisions owned by Harness and delivered in a later change.

Stakeholders are LLM routing and provider owners, Harness/workflow authors, global-budget and cache owners, operators reviewing route manifests, and future tokenizer adapter owners.

## Goals / Non-Goals

**Goals:**

- Produce one immutable, deployment-aware prepared request before a provider call.
- Count every token-affecting payload component through a provider-semantic normalizer.
- Resolve output reserve, operational limit, safety margin, and maximum input deterministically.
- Reject a deployment before provider I/O when its profile is absent, output limit is insufficient, or input does not fit.
- Select a compatible configured fallback for physical capacity failures without confusing them with transient provider retry.
- Give complete, stream, cache identity, global budget, events, and replay one prepared-request fingerprint and count breakdown.
- Normalize provider-reported context overflow as non-transient profile drift and bound any cross-deployment recovery.

**Non-Goals:**

- Selecting, truncating, summarizing, or otherwise mutating semantic context.
- Defining message groups, evidence-loss gates, Harness compaction plans, or verified context snapshots.
- Migrating every direct production `LLMClient` callsite; that remains a later stage-24 change.
- Implementing cache eligibility, lookup, write, single-flight, or stream replay from the cache-hardening change.
- Bundling a universal tokenizer for every OpenAI-compatible model. Exact/provider counters are injected through a port; the built-in fallback prioritizes safety over token efficiency.
- Letting model output, request metadata, cache state, or provider errors decide workflow quality, publication, memory writes, or tool authorization.

## Decisions

### 1. Harness owns semantic context; LLM preflight owns physical admission

`framework/harness/context` remains the only owner of protected content, evidence priority, compaction permission, summary verification, and replan/halt. `framework/llm/context` receives a complete `LLMRequest` and may normalize transport semantics, set the resolved deployment model, count it, and admit or reject it. It MUST NOT delete messages, tools, schema, evidence, or metadata to make a request fit.

This keeps deterministic physical facts close to model routing without leaking business quality decisions into provider code.

### 2. A versioned `ModelContextProfile` is separate from boolean capabilities

`ModelContextProfile` contains:

```text
provider
model
deployment_id
physical_context_window_tokens
max_output_tokens
default_output_tokens
tokenizer_family
tokenizer_revision
normalizer_revision
operational_input_fraction
safety_margin_tokens
provider_auto_truncation
profile_revision
```

All limits are strictly validated. Fractions must be in `(0, 1]`; token counts and revisions must be positive/non-empty where required; default output cannot exceed maximum output; and the profile identity must match its deployment. The router fails closed when no profile is available. A caller cannot supply or override the profile through `LLMRequest.metadata`.

The existing capability window/output fields remain readable for configuration migration, but the router consumes the resolved typed profile rather than treating capability integers as a full policy.

Alternative considered: extend `ModelCapabilities` with tokenizer and operational-policy fields. Rejected because provider capability flags, physical model limits, tokenizer revision, and rollout safety policy evolve independently.

### 3. Counting and provider dispatch share a provider-semantic normalizer

A normalizer converts `LLMRequest` plus resolved deployment model into the semantic payload used for counting and fingerprinting. OpenAI-compatible normalization covers messages, adapted tool schemas, response format/output schema, model, max output, and supported media descriptors. The provider client delegates payload construction to the same normalizer implementation or a shared pure helper.

Temperature and other response-affecting fields participate in the fingerprint even when they do not materially increase token count. Request metadata is excluded unless a typed metadata field is explicitly projected into provider payload.

Alternative considered: count the raw `LLMRequest.to_dict()`. Rejected because raw output schemas and tool definitions can differ from their provider representations, causing count and cache identity drift.

### 4. Token counting is a port with an explicit conservative fallback

`LLMTokenCounter` accepts the normalized payload and `ModelContextProfile`, and returns component counts for messages, tools, response schema/format, media, protocol overhead, and total input. Every result records method, tokenizer family, and revision.

`LLMTokenCounterRegistry` selects a counter by tokenizer family. When no exact/provider counter is registered and fallback is allowed, `ConservativeUTF8ByteTokenCounter` counts canonical UTF-8 bytes plus configured protocol overhead. It reports `method=conservative_fallback`; it is intentionally an upper bound for supported byte-fallback tokenizer families, not an exact estimate. Profiles for which byte counting is not a safe upper bound must disable this fallback and fail closed.

The old character-divide-by-four function remains temporarily for compatibility and diagnostics but is not used by router admission or global budget reservation.

Alternative considered: make `tiktoken` a mandatory core dependency. Rejected because NewsRoom supports non-OpenAI OpenAI-compatible deployments whose tokenizer families and revisions are not represented reliably by one package.

### 5. Output reserve is resolved before input admission

The effective budget is:

```text
operational_limit = floor(physical_limit * operational_input_fraction)
requested_output = request.max_tokens or profile.default_output_tokens
reserved_output = requested_output
max_input = operational_limit - reserved_output - safety_margin
```

If requested output exceeds `profile.max_output_tokens`, preflight returns `OUTPUT_LIMIT_EXCEEDED`; it does not clamp the request. If `max_input < 1`, the profile/policy combination is rejected. Admission passes only when `total_input_tokens <= max_input`.

Using the deployment maximum as an implicit default was considered but rejected because it reserves the entire output capacity for every unspecified request. A typed profile default makes the operational choice explicit and replayable.

### 6. Prepared request and admission are immutable, typed evidence

`PreparedLLMRequest` contains the normalized `LLMRequest`, normalized-payload fingerprint, deployment/profile/normalizer revisions, token count, effective budget, and `LLMContextAdmission`. Admission statuses are:

```text
ADMITTED
PROFILE_REQUIRED
OUTPUT_LIMIT_EXCEEDED
INPUT_LIMIT_EXCEEDED
COUNTER_UNAVAILABLE
PROVIDER_AUTO_TRUNCATION_FORBIDDEN
```

The fingerprint is a SHA-256 digest of canonical normalized payload plus deployment and profile identity. It never includes secrets or raw diagnostic metadata. A rejected prepared request is still useful as event/replay evidence but cannot be passed to a provider.

### 7. Router evaluates physical capacity per deployment before provider admission

For every configured deployment in route order, the router performs:

```text
deployment existence/enabled check
-> required capability check
-> model context profile resolution
-> normalize/count/output reserve/context admission
-> cache hook in the later cache change
-> cooldown and provider/global-budget admission
-> provider call
```

If a deployment is rejected for profile, output, or input capacity and a later configured deployment exists, the router records a capacity rejection and evaluates the next deployment. No provider call, cooldown mutation, provider attempt, or global-budget reservation occurs for the rejected deployment. A capacity fallback still re-runs all capability and policy checks.

Missing/disabled deployments and missing required functional capabilities preserve their existing fail-closed behavior; this change does not broadly turn configuration errors into fallbacks. Only typed physical-capacity outcomes authorize capacity fallback.

### 8. Complete and stream use the same preparation kernel

The router extracts shared route/deployment/preflight logic used by `complete()` and a new `stream()` method. Both pass the normalized request from the admitted prepared object to the provider client and emit the same preparation/admission evidence.

Streaming remains incremental: the router yields normalized provider events as they arrive, never buffers the full stream merely for preflight. A provider error before the first event may select a fallback only under the existing provider policy or the bounded context-overflow rule. Once user-visible stream events have been yielded, the router does not switch providers because that would splice two responses.

Global budget reserves the admitted `total_input_tokens`. Complete settles against response usage as today. Stream reserves before provider iteration and records provider usage through normalized usage events/terminal accumulation without attributing rejected-deployment counts.

### 9. Provider context overflow is non-transient and bounded

Provider adapters map HTTP 413 and recognized structured provider error codes for context/window overflow to `LLMProviderContextOverflow`, a subtype of `LLMProviderError` with `retryable=False` and canonical category `context_length`.

The provider client's internal retry loop never retries it. The router records local count, provider-reported bounded limit/usage when safely available, profile/tokenizer revisions, and drift. It does not update cooldown.

Before any user-visible output, the router may perform at most one controlled cross-deployment recovery when a later compatible deployment has a different usable profile. The request is re-prepared for that deployment. Re-dispatching the identical prepared payload to the same deployment is forbidden.

### 10. Events and manifests carry bounded preflight evidence

The existing `LLMRouterEventSink` is reused for:

```text
llm_context_profile_resolved
llm_request_prepared
llm_context_admission_decided
llm_context_capacity_fallback_selected
llm_provider_context_overflow_observed
```

Evidence includes deployment identity, revisions, count breakdown, budget values, status/reason, fingerprint, and `provider_call`. It excludes messages, prompt text, tool arguments/schema bodies, output schema bodies, credentials, and raw provider response bodies.

Route manifests and successful response metadata include the admitted prepared-request projection. Global budget uses the same admitted count, eliminating the legacy estimate split.

### 11. Cache consumes prepared identity but remains a separate owner

The active cache change may derive its key from the admitted payload fingerprint plus deployment/profile/normalizer/cache revisions. Context preparation occurs before cache lookup so a profile revision or normalization change cannot reuse an incompatible entry. A cache hit may bypass provider cooldown and provider-budget admission as specified by the cache change, but it does not bypass preparation, typed identity, Harness VERIFY, or logical request accounting.

No cache store/coordinator dependency is introduced by this change.

### 12. Legacy context APIs are deprecated without silent semantic changes

`LLMContextGuard` and `ContextPolicy` remain importable during this slice to avoid unrelated callsite breakage. Their truncate/summarize strategy values still only describe caller intent and MUST NOT mutate content. New router code does not call them. Removal or conversion to Harness-owned compaction is handled by the next stage-24 change with explicit tests.

## Risks / Trade-offs

- **[Conservative byte fallback rejects requests that might fit]** -> Report method/revision, support exact counter injection, measure rejection/drift, and never label fallback counts exact.
- **[Normalizer and provider client drift]** -> Share pure payload helpers and add golden tests that compare counted/fingerprinted payload with dispatched payload.
- **[Strict profile requirement breaks old router tests/config]** -> Update router fixtures and model config validation in the same change; direct clients remain available until callsite convergence.
- **[Capacity fallback increases cost or changes data handling]** -> Only configured route deployments are eligible and all existing capability/policy checks rerun.
- **[Stream fallback can splice output]** -> Permit fallback only before the router yields the first user-visible provider event.
- **[Provider 400 errors are ambiguous]** -> Recognize context overflow only from HTTP 413 or bounded structured provider codes; do not keyword-match arbitrary messages.
- **[Concurrent cache implementation changes router internals]** -> Keep prepared request as a framework-owned value object and cache orchestration as a separate injected concern; rebase against the live router before each implementation commit.
- **[Current direct production clients still bypass the router]** -> Document this slice as router enforcement, then close callsites in the dedicated third stage-24 change; do not overstate global enforcement at this stage.

## Migration Plan

1. Add profile, budget, token-count, normalizer, prepared-request, and admission models with unit tests.
2. Add strict context-profile configuration parsing and migration from existing capability window/output values when complete inputs are present.
3. Add the OpenAI-compatible shared payload normalizer and switch the provider client to it without changing wire payloads.
4. Integrate preparation/admission into router complete, update global-budget reservation, and add capacity fallback events/manifests.
5. Add router stream using the shared kernel and verify no fallback after visible output.
6. Normalize provider overflow and add bounded cross-deployment recovery/drift evidence.
7. Run observe/shadow comparisons against provider usage, then enable strict router admission.
8. Roll back by disabling router composition for affected callsites, not by restoring provider-side overflow as the normal guard. Versioned profile/config and event schemas remain readable.

## Open Questions

- Exact tokenizer adapters for each production model family will be delivered as independently registered adapters after the registry contract is stable. Until then, only profiles that explicitly allow the conservative byte fallback can be admitted without an exact counter.
- Provider-reported token-limit fields vary by API. The first implementation records only explicitly mapped structured fields; expanding mappings requires adapter tests and a profile/normalizer revision bump.
