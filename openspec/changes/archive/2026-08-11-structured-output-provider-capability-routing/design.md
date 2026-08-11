## Context

Change 1 established one immutable local contract and strict terminal validator. Change 2 must describe what a resolved deployment can enforce without weakening that local truth. Existing `ModelCapabilities.supports_structured_output` is insufficient because it cannot identify dialect, keyword coverage, local-reference support, schema limits, stream terminal safety, or a reviewed revision.

The router already owns ordered deployment fallback and model-aware context preflight. Provider projection therefore belongs immediately after deployment resolution and before context preparation. The HTTP adapter receives the resulting projection through the request execution context and never selects a weaker mode on its own.

## Decisions

### Versioned deployment capability

`ProviderStructuredOutputCapability` records provider/deployment identity, one reviewed enforcement mode, supported dialect and keywords, local-reference and resource limits, stream terminal support, and a non-empty revision. Configuration loading validates identity and rejects implicit or malformed profiles.

### Pure, fail-closed projection

`project_structured_output_contract()` inspects the canonical schema without rewriting it. Native or constrained modes are eligible only when dialect, limits, references, and every enforcement keyword used by the contract are covered. JSON-object local-gate mode is available only when explicitly allowed by request policy; it sends no provider schema and reports every locally enforced keyword as omitted by the provider. Rejected projections carry bounded diagnostics and never reach transport.

Projection digest binds contract digest, capability revision, mode, provider schema, and sorted coverage sets. Canonical local schema remains unchanged.

### Router ordering and fallback

The router compiles once before any deployment attempt. Each attempt independently resolves capability and projection, records selected/rejected metadata, then performs stage 24 context preparation against the projected provider payload. Ineligible primary deployments continue to configured fallbacks. The final ineligible attempt raises a non-retryable route error with provider-call count zero for those attempts.

### Client execution context

`LLMRequest` preserves private immutable compiled-contract/projection execution context across normalization clones while serializing only stable public request fields. Managed router requests always carry both. A directly constructed client may use an explicitly injected capability profile, but no default native-strict capability is inferred from provider name or an API response.

### Complete/stream terminal parity

The OpenAI-compatible client maps only the chosen projection to `response_format`. Complete and stream terminal paths call one shared structured-output terminal gate. Stream text/tool fragments are emitted with `provisional=True`; the final event is emitted only after the accumulated text passes strict decode, local schema validation, and optional typed validation. The terminal event carries the validated object and the same contract/projection metadata as complete. Incomplete or invalid streams never emit a verified terminal event.

### Constrained capability boundary

The projection model can represent a reviewed constrained-decoding deployment. Core code does not implement grammar/FSM decoding. An adapter must explicitly implement its constrained projection mapping; the OpenAI-compatible adapter supports only its declared JSON-schema and JSON-object mappings and fails closed for an incompatible constrained projection.

## Risks and Mitigations

- Existing direct structured client tests may rely on implicit native strict behavior. They will inject an explicit tested capability profile.
- Stream consumers may have treated deltas as final data. Provisional metadata and terminal-only validated objects make the distinction observable without removing text streaming.
- Capability keyword inventories can drift. Strict configuration validation, projection digests, and protocol tests bind behavior to a reviewed revision.

## Out of Scope

- Cache identity/revalidation and Harness repair/event convergence are Change 3.
- Provider evaluation, promotion, rollout, and rollback records are Change 4.
- No grammar decoder or provider capability discovery is implemented in framework core.
