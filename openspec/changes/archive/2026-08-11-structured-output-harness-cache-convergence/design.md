## Context

Change 1 established an immutable local `StructuredOutputContract`; Change 2 added deployment-specific projection and complete/stream terminal parity. The remaining production path has three gaps: cache entries do not persist an explicit contract identity, `OutputJudge` emits only strings instead of stable diagnostics, and the Research candidate worker repeats schema validation after the client has already accepted output.

Stage 23 owns cache isolation and corruption handling. Stage 19 owns durable workflow events. This change integrates with those owners rather than creating a second store or event system.

## Decisions

### Explicit cache contract identity

`StructuredOutputCacheIdentity` is derived only from the compiled contract and selected projection. It includes schema digest/revision, dialect, typed-adapter revision, provider capability revision, projection digest, and projection mode. The cache key binds the identity and the cache entry persists the exact same identity. A request without a compiled managed contract is ineligible for structured-output caching.

Every write validates the terminal object through the compiled contract before projection. Every hit verifies entry identity and revalidates the restored object. A mismatch or validation failure is a corrupt miss and is deleted best effort. Cache hits remain candidates for later domain/evidence gates.

### Standard observability envelope

Framework structured-output stages emit immutable `StructuredOutputEvent` values through an injected sink. The event schema is allowlisted and redacted: run/attempt reference, schema/capability/projection identities, bounded issue code and paths, issue count, response fingerprint, budget disposition, timestamp, and duration. Raw output, schema bodies, prompts, tenant names, secrets, tool payloads, and evidence are rejected.

Metrics are low-cardinality counters/histograms derived from the same events. Digest/path/name fields are never metric labels. Router metadata remains attempt-local evidence; workflow integration records the safe events through the existing recorder and Stage 19 durable bridge.

### Harness-owned bounded repair

`OutputJudge` compiles the AgentSpec schema once per judge call through the canonical compiler and returns stable diagnostic dictionaries on `JudgeVerdict`. It continues to run rule, policy, domain, and evidence validators after schema success. `AgentLoop` emits one `structured_output_repair_requested` event only when a schema/typed diagnostic caused a retry, increments its existing judge retry budget, detects an unchanged rejected output fingerprint, and deterministically halts through the existing retry-exhausted state when no useful bounded attempt remains.

The diagnostic feedback supplied to the next worker attempt is capped and contains codes and JSON Pointer paths only. The worker cannot choose routing, accept itself, reset budget, or write durable state.

### Research convergence

`ResearchCandidateWorker` accepts only a managed `LLMResponse` whose structured-output validation metadata matches the task contract. It performs no second JSON Schema interpretation. It then applies its existing deterministic scope/evidence checks. Contract failure maps to a candidate-output error and cannot reach report/artifact publication.

### Architecture closure

Production source inventory is enforced by an AST-based architecture test. Outside the structured-output/cache owners, production code may consume `response.structured_output` only after checking the managed validation envelope and may not call `json.loads(response.content)` or the compatibility `validate_structured_output()` API for LLM output.

## Risks and Mitigations

- Cache hit rate changes when contract or capability revisions change. This is intentional isolation; tests prove stable identity for equivalent contracts.
- Existing fake clients may omit validation metadata. Test fakes receive explicit managed envelopes; production callers fail closed.
- Event fan-out could leak high-cardinality data. The event constructor enforces an allowlist and metrics use only bounded labels.

## Out of Scope

- Provider/schema corpus evaluation, promotion flags, shadow mode, and rollback records are Change 4.
- This change does not add a new durable event store or a second retry scheduler.
- Business domain and evidence gates remain owned by their current services and validators.
