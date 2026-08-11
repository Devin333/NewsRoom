## 1. Contracts, Policy, and Bounded Memory

- [x] 1.1 (CACHE-001) Add framework cache contracts for `CacheScope`, dependency/context parsing, versioned `LLMCacheKey`, typed lookup/write outcomes, cache entry identity, and owner-token single-flight leases; expose them from `framework.llm.cache` without infrastructure imports.
- [x] 1.2 (CACHE-002) Implement versioned canonical semantic payload construction and domain-separated HMAC key generation for scope, deployment, and request identity; reject unsupported values and retain unknown metadata conservatively.
- [x] 1.3 (CACHE-003) Replace boolean-only cache policy with deterministic mode-aware eligibility decisions covering task/agent allowlists, scope, dependency revisions, temperature/seed, tools, freshness/side-effect markers, output contract, and stable reason codes.
- [x] 1.4 (CACHE-004) Replace the unbounded memory dictionary with a bounded, thread-safe, monotonic-clock, LRU, TTL, byte-limited `InMemoryLLMCache` implementing store and owner-token lease contracts with isolated return values.
- [x] 1.5 (CACHE-005) Add versioned safe response projection/entry encoding and a shared deterministic cache-write validator that rechecks current response format/output schema, rejects tool calls and unsafe fields, and reconstructs a fresh response on read.
- [x] 1.6 Add focused contract tests for canonicalization, HMAC redaction, scope/deployment/generation isolation, eligibility reasons, safe projection, schema validation, memory TTL/LRU/size/deep-copy/thread safety, and stale-owner release protection.

## 2. Router, Accounting, Events, and Composition Boundary

- [x] 2.1 (CACHE-010) Inject an optional framework cache runtime into `LLMRouter` and move exact lookup into each deployment attempt after enabled/capability validation and before cooldown/global provider budget admission.
- [x] 2.2 (CACHE-011) Implement deployment-specific hit/miss/bypass decoration and primary/fallback identity isolation; remove reuse of stale call/run/event metadata from cached responses.
- [x] 2.3 (CACHE-012) Add explicit logical-request versus physical-provider-call accounting to router traces/budget interaction while preserving existing `max_llm_calls`, provider token/cost, cooldown, and fallback semantics on miss/bypass paths.
- [x] 2.4 (CACHE-013) Emit redacted cache lifecycle evidence through existing `LLMRouterEventSink` for eligibility, lookup, hit, miss, bypass, corruption, single-flight, backend failures, and writes.
- [x] 2.5 (CACHE-014) Add typed cache runtime settings and an explicit composition factory that injects framework ports into the router, creates no backend under `disabled`, and keeps endpoints/business/provider clients from creating cache singletons.
- [x] 2.6 (CACHE-040) Implement `disabled`, `observe`, `write_only`, and `read_write` mode behavior with per-task allowlists and no behavior change in disabled mode.
- [x] 2.7 (CACHE-042) Remove the client-owned production cache wrapping path or reduce it to a documented non-production compatibility boundary; ensure no production route runs duplicate client and router cache lifecycles.
- [x] 2.8 Add router/budget/fallback/event tests for cooldown-hit ordering, disabled/capability rejection, global-budget bypass on hit, logical/provider counters, cache failure fail-open, stale metadata stripping, fallback isolation, modes, and framework import direction.

## 3. Redis Store, Codec, and Single Flight

- [x] 3.1 (CACHE-020) Implement `RedisLLMCache` under `infrastructure/storage` using only dedicated keys/namespace, finite TTL, bounded values, typed outcomes, best-effort corrupt deletion, and no `KEYS` operations.
- [x] 3.2 Add cache-specific deterministic envelope codec with AEAD encryption, associated-data binding, version checks, size limits, and redacted errors; inject separate HMAC and encryption secrets.
- [x] 3.3 (CACHE-021) Implement Redis owner-token single-flight acquire, bounded waiter recheck, compare-and-delete Lua release, lease expiry recovery, and timeout/error outcomes.
- [x] 3.4 (CACHE-022) Add environment-backed Redis cache settings, startup validation for URL/secrets/TLS/TTL/size/timeouts/lease relationship, `.env.example` documentation, and disabled-mode lazy construction.
- [x] 3.5 (CACHE-023) Add operator-facing cache readiness/health contract, ACL/TLS guidance, bounded prefix-only validation, namespace/eviction documentation, generation-bump invalidation procedure, and no runtime-store coupling.
- [x] 3.6 Add infrastructure tests with fake Redis for round trips, tampering/wrong keys/versions, oversize values, expiry, backend errors, atomic release race, lease recovery, prefix isolation, and configuration validation; add opt-in real Redis marker tests gated by explicit environment variables.

## 4. Streaming Cache and Replay

- [x] 4.1 (CACHE-030) Add router-aware `stream()` orchestration using the same policy/key/lookup/single-flight/cooldown/budget/fallback path as `complete()`, accumulating only normal complete source streams.
- [x] 4.2 (CACHE-031) Implement bounded normalized cache-hit replay from a safe `LLMResponse` as `message_start`, text chunks, optional source-usage event, and one `message_complete`, with fresh current-call metadata and zero current provider usage.
- [x] 4.3 (CACHE-032) Enforce no-write behavior for source errors, malformed ordering, missing/duplicate completion, tool events/calls, consumer early close/cancellation, validation failure, oversize, and write failure after a successful stream.
- [x] 4.4 Add stream tests proving incremental miss delivery, completed write once, accumulator-compatible replay, no provider call/cooldown/provider-budget mutation on hit, no cached partial/tool stream, cancellation behavior, and cache-write failure isolation.

## 5. Documentation, Validation, Rollout, and Archive

- [x] 5.1 (CACHE-041) Update configuration documentation, cache rollout/runbook guidance, generation/key-version bump procedures, targeted invalidation boundaries, rollback-to-disabled behavior, and secret handling.
- [x] 5.2 Add regression tests proving no raw prompt/response/tool arguments/scope/secret/full key are present in cache entries, exceptions, router events, or metric payloads.
- [ ] 5.3 (CACHE-043) Run and fix `python -m scripts.dev compile`, focused framework and infrastructure cache tests, relevant broad LLM/storage tests, `python -m scripts.dev smoke`, `openspec validate llm-cache-production-hardening --strict`, and `git diff --check`.
- [ ] 5.4 Mark completed OpenSpec tasks only after their implementation and test evidence pass; archive the change only after every deterministic acceptance gate and production wiring deletion is verified.
