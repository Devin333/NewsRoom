## Context

NewsRoom currently exposes exact-response caching through `CachedLLMClient`, backed by an unbounded `InMemoryLLMCache`. The wrapper is invoked only after `LLMRouter` has already evaluated cooldown and reserved global provider budget, so it cannot implement the required cache-hit accounting or primary/fallback semantics. The existing key is an unkeyed digest of the full request and lacks tenant, deployment, generation, and revision isolation. The memory store has no production capacity or concurrency contract, and no stream path exists.

This change spans framework contracts, router control flow, infrastructure storage, configuration, security, event evidence, and tests. The cache remains an optimization under Harness/router control. It must never decide workflow routing, quality pass/fail, tool authorization, memory writes, or publication.

Relevant constraints:

- `LLMClient`, `LLMRouter`, and cache ports are synchronous. Cache adapters must not hide unbounded background work.
- Provider cooldown, fallback, route budget, and global provider budget semantics must remain authoritative on misses.
- Cache failures are fail-open to the existing provider path, while untrusted entries fail closed as misses.
- Framework code must not import Redis or other infrastructure implementations.
- Existing `LLMRouterEvent` evidence is extended rather than replaced by a second transcript system.
- Production cache state is disposable and must be isolated from durable runtime, event, artifact, and business facts.

## Goals / Non-Goals

**Goals:**

- Provide a versioned, scope-bound, HMAC-keyed exact-response cache for deterministic LLM requests.
- Perform cache lookup inside the deployment loop after enabled/capability checks and before cooldown/provider budget admission.
- Separate logical request accounting from physical provider calls, token usage, cost, and cooldown mutation.
- Validate and project complete responses deterministically before storage; never cache tools, unsafe metadata, raw provider payloads, or incomplete streams.
- Provide bounded, thread-safe memory behavior and a dedicated encrypted Redis backend with atomic single-flight coordination.
- Support normalized replay of completed streaming responses.
- Provide typed configuration, fail-fast startup validation, stable reason codes, durable router events, and reversible rollout modes.

**Non-Goals:**

- Semantic or approximate matching.
- Provider-native prompt-cache control or accounting.
- Replaying tool calls or side-effect candidates.
- Caching live/latest/current-time research, arbitrary agent conversations, evidence records, or workflow decisions.
- Durable reporting, analytics storage, or cross-tenant sharing.
- A tiered local-plus-Redis consistency protocol.
- A compatibility layer that keeps client-owned production caching active indefinitely.

## Decisions

### 1. Router owns cache orchestration through framework ports

`LLMRouter` receives an optional framework-owned cache runtime containing `LLMCacheStore`, `SingleFlightCoordinator`, `LLMCachePolicy`, `LLMCacheKeyFactory`, and response codec/validator collaborators. A disabled or absent runtime preserves the existing path without creating a backend connection.

For each deployment, the router order is:

1. validate deployment enabled and required capabilities;
2. evaluate deterministic eligibility and construct the deployment-specific key;
3. perform an exact lookup when the rollout mode permits reads;
4. return a valid hit with current-call metadata and evidence;
5. coordinate a bounded single-flight miss and recheck;
6. evaluate cooldown and provider/global/route budgets;
7. call the selected provider;
8. validate the response against the current request and settle provider accounting;
9. write only a safe, complete response when the mode permits writes;
10. emit final route/cache evidence and return.

This order lets a valid primary entry survive a temporary primary cooldown, while disabled or capability-incompatible deployments remain unusable. Alternatives considered were keeping `CachedLLMClient` as the production owner and placing cache lookup before deployment validation. The former cannot bypass router admission or isolate fallback identity; the latter would permit consumption of disabled/incompatible deployments.

### 2. Cache context is explicit and typed at the framework boundary

The request carries a reserved cache context in metadata for compatibility with the existing immutable `LLMRequest` contract. Framework code parses it into immutable `CacheScope` and `CacheDependencies` values before eligibility or keying. Required scope fields are `tenant_id`, `project_id`, and a non-empty `policy_scope`; required dependency names are configured per task policy. Missing or malformed values result in a stable bypass reason and never a global default.

Semantic metadata is selected by a versioned classifier. Diagnostic metadata such as run/call/trace IDs is excluded. Scope values are HMACed and never serialized into entries or evidence. Unknown metadata is treated as semantic input by canonicalization instead of silently ignored, preventing unsafe false hits at the cost of conservative misses.

An alternative was adding tenant and revision fields directly to `LLMRequest`. That would widen every client contract and duplicate concerns that are specific to caching. A typed parser around a reserved metadata envelope preserves explicit validation while limiting API churn.

### 3. Keys use versioned canonical JSON and domain-separated HMAC

The key factory canonicalizes request semantics without `repr` or lossy coercion. It distinguishes missing, `null`, empty string, booleans, integers, and floats; preserves list order; sorts mapping keys; normalizes supported dataclass/model values through their public dictionaries; and rejects unsupported values with a bypass reason.

Separate HMAC contexts derive scope, deployment, and request digests using `NEWS_LLM_CACHE_KEY_SECRET`. The external key contains only namespace, key version, short scope/deployment digests, and a full request HMAC. It binds provider, model, deployment ID, cache generation, messages, generation settings, tools, response contract, dependency revisions, and semantic metadata. Key-format or classifier changes require a key-version bump.

Bare SHA-256 was rejected because an operator with cache-key access could dictionary-test sensitive prompt or scope material. Encrypting the request itself was rejected because requests are not stored at all.

### 4. Entries are minimal versioned envelopes validated for the current request

`CacheEntry` stores creation time, key/schema versions, source deployment identity, source usage, and a safe response projection. The projection preserves content, structured output, model, usage, empty tool calls, and an allowlisted subset of result metadata. It removes `raw`, headers, credentials, trace/run/call IDs, request metadata, and prior route/cache event lists.

Before a write, shared deterministic validation re-evaluates the response against the current `response_format`, `output_schema`, and `output_schema_name` by using the framework structured-output validator. It rejects any response containing tool calls or unsafe/non-serializable fields. Cached reads reconstruct a fresh `LLMResponse`, recheck entry/key/schema/deployment versions and policy constraints, and decorate it only with current-call metadata.

Trusting provider-client metadata was rejected because `LLMClient` implementations, fakes, and future adapters do not share a proof boundary. Storing `LLMResponse.raw` was rejected because it expands secret and provider-coupling risk without being needed for replay.

### 5. Lookup results and failures are explicit, with fail-open orchestration

The store returns a typed `CacheLookup` with `hit`, `miss`, `expired`, `corrupt`, or `backend_error` status. Writes return a typed result. Infrastructure exceptions do not escape through the framework port unless startup configuration is invalid. Corrupt, unverifiable, or unknown-version entries are deleted best-effort and treated as misses; backend errors are recorded and bypassed.

This distinction is required for diagnostics and security response. Returning only `None` was rejected because it makes corruption and outages indistinguishable from normal misses.

### 6. Memory backend is bounded and implements the same lease contract

The in-memory backend uses a re-entrant lock, monotonic clock injection, LRU ordering, finite `max_entries`, optional `max_bytes`, finite TTL in production-like use, deep-copy/serialization isolation, and owner-token leases. Expired entries and leases are removed lazily under the lock. A stale owner cannot release a replacement lease.

The memory backend remains suitable for tests and explicit development composition only. It is not a multi-process production substitute.

### 7. Redis is a dedicated adapter with authenticated encryption

`RedisLLMCache` lives under `infrastructure/storage` and implements the framework ports without depending on `RedisRuntimeStore`. It uses a dedicated URL, ACL-scoped namespace, bounded key names, finite TTL, maximum encoded entry size, and no `KEYS` scan. Payloads are encoded deterministically and protected with cache-specific AEAD using `NEWS_LLM_CACHE_ENCRYPTION_KEY`; associated data binds namespace, key, and schema version. Key HMAC and payload encryption use separate secrets.

Redis transport must use TLS outside an explicitly declared local/test mode. Startup validates URL, secrets, sizes, timeouts, namespace, and TTL relationships. Runtime Redis timeout/unavailability is fail-open and never converts a provider failure into success. Redis restart, eviction, or flush only produces misses.

Reusing the generic runtime store was rejected because its key enumeration, optional TTL, and lock lifecycle do not provide the cache-specific isolation and atomic owner semantics.

### 8. Single-flight uses owner-token leases and bounded double-check

The coordinator performs atomic acquire with `SET NX PX`, carries an unguessable owner token, and releases through a compare-and-delete Lua script. A waiter polls only until the minimum of the configured wait timeout and caller deadline, rechecking the cache between polls. Lease TTL exceeds the provider timeout plus a safety margin; expiry permits takeover. Only the current owner may write the coordinated result.

After wait timeout, fail-open mode continues through the normal provider admission path without writing unless it later owns a lease. The router never waits indefinitely and never extends a caller deadline. An unconditional `GET` then `DEL` release was rejected due to the old-owner/new-owner race.

### 9. Logical and physical accounting are separate

Every router invocation records one logical request. Only an actual provider call reserves/increments `max_llm_calls`, provider tokens, cost, and cooldown state. A cache hit sets `llm_provider_call=false`, `llm_budget_cost_counted=false`, and does not run global provider-budget preflight or settlement. Miss and bypass paths preserve current provider accounting.

Source usage stored in a cached response describes the original result and is exposed separately from current-call provider usage. It is not added to the current provider budget. Existing provider-budget field meanings remain unchanged; a separate logical-request limit can be introduced without redefining `max_llm_calls`.

### 10. Streams cache only a completed accumulated response

The cache-aware stream path normalizes each source event through `LLMStreamEvent.from_any`, validates exactly one `message_start` and one terminal `message_complete`, feeds an `LLMStreamAccumulator`, and yields provider events without delaying them. A cache write is attempted only after the source iterator ends normally after the unique completion event, the consumer has not cancelled/closed early, no error/tool event occurred, and the accumulated response passes the same deterministic write validator.

On a hit, the router emits a new normalized sequence: `message_start`, bounded `text_delta` chunks, optional `usage_delta` representing source-result metadata, and `message_complete`. Replay does not reproduce provider timing or chunk boundaries and marks all current-call provider usage as zero. Provider chunks themselves are never stored.

### 11. Rollout modes are deterministic and reversible

The typed modes are:

- `disabled`: no eligibility work, backend construction, lookup, or write;
- `observe`: evaluate policy/key and emit evidence without backend read/write;
- `write_only`: evaluate and write eligible provider successes without serving hits;
- `read_write`: serve and populate eligible exact entries.

Task policy remains an explicit allowlist and defaults to empty. Mode changes do not alter route resolution, fallback, or Harness verification. Rollback sets `disabled`; unsafe content/model/policy changes bump generation/version or namespace rather than scanning/deleting synchronously on request paths.

### 12. Events are current-call evidence, not workflow decisions

The router reuses `LLMRouterEventSink` for eligibility, lookup, hit/miss, wait, bypass, corruption, write, and backend-error events. Events contain route/deployment, mode, version, stable reason, provider-call flag, duration, size bucket, and a bounded short digest only. They never contain raw prompt/response, scope text, tool arguments, secrets, or the full external key.

The Harness transcript may project these events as evidence, but a hit does not imply VERIFY success or authorize publication.

### 13. Configuration is loaded separately and composed explicitly

A typed cache-settings loader owns the `llm_cache` schema and environment references rather than silently extending arbitrary deployment metadata. Production composition creates a Redis adapter only when mode is not `disabled` and backend is `redis`, then injects framework ports into the router. Missing secrets/URL, unsupported mode/backend, invalid TTL/size/wait ranges, insecure transport, or lock TTL shorter than provider timeout plus margin fail at startup.

No endpoint, business worker, or provider client creates a global cache singleton. This preserves framework-to-infrastructure dependency direction and makes tests replace the backend through ports.

## Risks / Trade-offs

- [Risk] Conservative metadata classification causes false misses. -> Keep unknown fields semantic, expose stable bypass/miss evidence, and bump key version when the classifier changes.
- [Risk] A Redis lookup adds latency to misses. -> Use bounded timeouts, colocated Redis, fail-open behavior, and staged observe/write-only rollout before reads.
- [Risk] Lease expiry can still permit duplicate provider calls for unusually slow calls. -> Size lease TTL above provider timeout, cap caller/provider deadlines, record takeover metrics, and rely on exact writes being idempotent.
- [Risk] Synchronous polling consumes a worker briefly. -> Bound wait by both caller deadline and a small configured timeout; do not create hidden threads.
- [Risk] Source usage in a cached response can be confused with current cost. -> Preserve it under explicit source-result metadata and set current provider-call/cost flags to false.
- [Risk] Encryption-key rotation invalidates unread entries. -> Treat cache as disposable, bump key version/namespace, and permit only an explicitly time-bounded dual-read migration if required.
- [Risk] A new cache context in metadata is populated inconsistently. -> Provide typed constructors/validators, require scope/dependencies per task policy, and bypass when absent rather than invent defaults.
- [Risk] Stream consumers can abandon generators without a terminal callback. -> Write only after normal generator exhaustion and completion; early close and cancellation leave no entry.
- [Risk] Cache events could become high cardinality or leak data. -> Enforce an allowlisted event projection and only short keyed digests.

## Migration Plan

1. Add framework contracts, keying, policy, entry projection/validation, and bounded memory backend behind `disabled` mode; keep existing behavior as the baseline.
2. Integrate cache orchestration into `LLMRouter`, add logical/provider accounting and events, and prove disabled-mode parity plus cooldown/budget ordering in tests.
3. Add dedicated Redis codec/store/coordinator and typed configuration; validate encryption, corruption, timeout, lease races, and process-shared behavior.
4. Add complete-stream accumulation and normalized replay with cancellation/error tests.
5. Roll out `observe`, then `write_only`, then `read_write` for reviewed task types with explicit scope/dependency contracts.
6. Remove client-owned production composition and retain `InMemoryLLMCache` only as an explicitly injected development/test backend.
7. Run focused and broad tests, compile, smoke, and strict OpenSpec validation. Archive only after all tasks and deterministic gates pass.

Rollback is a configuration change to `disabled`. If an entry population is suspect, bump `cache_generation`, key version, or namespace. Do not delete durable runtime data or perform unbounded cache scans.

## Open Questions

- None blocking implementation. The initial production composition uses a dedicated environment-backed cache settings loader; broader model-config consolidation can be a later change.
