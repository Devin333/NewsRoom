## Why

NewsRoom's existing LLM cache is a development-only `InMemoryLLMCache` attached below the router. It does not provide a stable request scope, authenticated key material, bounded storage, production lifecycle, or router-level accounting semantics. As a result, a cache hit can still be preceded by cooldown and budget decisions, concurrent identical requests can stampede providers, and a response can be replayed without proving that it is safe for the current tenant, task, schema, or tool context.

The production runtime needs an exact-response cache owned by the Harness control plane. It must preserve the existing provider fallback and budget contracts while making cache use observable, fail-open, and safe to disable or roll back.

## What Changes

- Add a scope-bound exact response cache contract for eligible, deterministic LLM requests. Cache keys include tenant/run/task and request semantics, are versioned, and use keyed hashing so raw prompts and secrets are not used as identifiers.
- Move cache lookup into `LLMRouter` before cooldown and provider/global budget admission. A valid hit returns without consuming provider budget; logical request metrics and physical provider-call metrics remain separate and explicit.
- Add deterministic response validation before writes, including structured-output schema checks and metadata/tool-call safety projection. Invalid, partial, streamed, or unsafe responses are never cached.
- Replace unbounded development-only memory behavior with a bounded thread-safe in-memory backend and a dedicated Redis backend. Redis uses a cache-specific namespace, TTL and size limits, authenticated encryption/integrity, atomic single-flight ownership, and fail-open behavior. It must not reuse the generic runtime pointer/lock store as its cache protocol.
- Support complete stream response caching and normalized event replay without replaying provider timing or exposing mutable internal state.
- Add configuration, composition-root wiring, observability, rollout modes (`disabled`, `observe`, `write_only`, `read_write`), and tests covering cross-scope isolation, cooldown/budget ordering, fallback, concurrency, corruption, eviction, restart behavior, and stream replay.
- Remove production reliance on the client-only cache wrapper; retain compatibility only where required by the active migration contract.

## Capabilities

### New Capabilities

- `llm-response-cache`: exact-response cache policy, keying, safe entries, deterministic validation, bounded local storage, and fail-open cache operations.
- `llm-router-cache-integration`: router-level lookup/admission ordering, logical versus physical accounting, fallback interaction, rollout modes, and cache observability.
- `llm-cache-redis-backend`: dedicated Redis namespace, TTL/size policy, authenticated encrypted entries, atomic single-flight, and restart-safe behavior.
- `llm-stream-cache-replay`: complete stream capture, normalized replay, and protection against partial or mutable event reuse.

### Modified Capabilities

- None.

## Impact

The change affects `framework/llm` contracts, policy/key/entry/backends, `LLMRouter` integration, stream accumulation, and composition-root configuration. It adds a dedicated cache adapter under `infrastructure`, cache-specific environment/configuration fields, metrics/events, and focused unit/integration tests. No business-layer dependency on legacy boards, interfaces, or runtime pointer storage is introduced. Provider calls remain the only source of physical cost and continue to be governed by the router's existing cooldown, fallback, and budget mechanisms on misses.
