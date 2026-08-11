## ADDED Requirements

### Requirement: Cache is disabled by default and exact-only
The framework SHALL default LLM response caching to `disabled`, SHALL require an explicit task allowlist before any request is eligible, and SHALL support exact canonical matching only. It MUST NOT perform semantic matching, cross-task reuse, or provider-native prompt-cache control.

#### Scenario: Default configuration bypasses caching
- **WHEN** a router is created without an enabled cache policy
- **THEN** the request follows the existing provider path without constructing a cache key, reading a backend, or writing an entry

#### Scenario: Similar but non-identical requests do not match
- **WHEN** two requests differ in any canonical semantic field
- **THEN** they produce different exact keys and the second request cannot reuse the first response

### Requirement: Eligibility is deterministic and reason-coded
`LLMCachePolicy` SHALL return a typed eligibility decision with a stable reason code. A request SHALL be eligible only when its task is explicitly allowlisted, cache scope is complete, required dependency revisions are present, temperature is deterministically allowed, tools are absent, the task is not freshness-sensitive or side-effect-capable, and the output contract is supported. Unknown or malformed policy input MUST fail closed to bypass.

#### Scenario: Eligible deterministic request
- **WHEN** an allowlisted request has temperature zero, no tools, complete scope, all configured dependency revisions, a supported output contract, and no freshness or side-effect marker
- **THEN** policy returns eligible with a stable eligible reason

#### Scenario: Missing scope is bypassed
- **WHEN** tenant, project, or policy scope is missing or empty
- **THEN** policy returns ineligible with `missing_cache_scope` and no backend lookup occurs

#### Scenario: Nondeterministic or tool-capable request is bypassed
- **WHEN** a request has a nonzero temperature, declares tools, contains a side-effect-candidate marker, or represents a live/latest task
- **THEN** policy returns the corresponding stable bypass reason and the response is never cached

#### Scenario: Dependency revision is required
- **WHEN** a task policy requires a prompt, evidence, source, or retrieval revision that the request does not provide
- **THEN** policy returns `missing_dependency_revision`

#### Scenario: Unknown metadata remains conservative
- **WHEN** request metadata contains an unclassified value that cannot be canonically represented
- **THEN** the cache path bypasses with a stable unsupported-metadata reason rather than discarding the value

### Requirement: Cache scope is explicit and isolated
Every eligible request SHALL resolve an immutable `CacheScope` containing non-empty tenant, project, and policy-snapshot identifiers. Scope values MUST be included only through a domain-separated keyed digest and MUST NOT appear in external keys, cache values, logs, metrics, or router events.

#### Scenario: Cross-tenant isolation
- **WHEN** two otherwise identical requests use different tenant, project, or policy scopes
- **THEN** they produce different cache keys and cannot read each other's entries

#### Scenario: Scope text is not exposed
- **WHEN** a key, lookup result, event, metric payload, or exception is rendered
- **THEN** no raw tenant, project, or policy-snapshot identifier is present

### Requirement: Cache keys are versioned canonical HMAC identifiers
The key factory SHALL use a versioned canonical JSON representation and domain-separated HMAC digests for scope, deployment, and request identity. The request identity MUST bind messages, provider, model, deployment ID, route/cache generation, generation settings, tools, response format, output schema and name, dependency revisions, and semantic metadata. Missing, null, empty, boolean, integer, float, mapping, and sequence values MUST retain distinct canonical meanings.

#### Scenario: Mapping order is stable
- **WHEN** semantically identical mappings are supplied with different insertion order
- **THEN** the canonical representation and resulting key are identical

#### Scenario: Semantic identity changes invalidate the key
- **WHEN** scope, deployment, provider, model, generation, version, message content, dependency revision, output schema, or another semantic field changes
- **THEN** the resulting key differs

#### Scenario: Key contains no raw request material
- **WHEN** an external cache key is rendered
- **THEN** it contains only the bounded namespace/version and keyed digests, with no prompt, raw scope, secret, or full request JSON

#### Scenario: Unsupported canonical value bypasses safely
- **WHEN** a semantic value has no versioned canonical representation
- **THEN** key construction returns an explicit bypass decision and MUST NOT fall back to Python `repr`

### Requirement: Cache entries use a minimal versioned response envelope
Cache values SHALL use a versioned `CacheEntry` envelope containing creation time, key/schema versions, source deployment identity, source result usage, and a safe response projection. The projection SHALL be sufficient to reconstruct a fresh `LLMResponse` while excluding raw provider payloads, headers, credentials, request content, tracebacks, run/call/trace identifiers, and prior routing/cache events.

#### Scenario: Safe response round trip
- **WHEN** an eligible text or structured response is projected, serialized, deserialized, and reconstructed
- **THEN** content, structured output, model, source usage, and safe metadata are preserved and tool calls remain empty

#### Scenario: Unsafe fields are stripped
- **WHEN** a provider response contains `raw`, headers, credentials, request-scoped metadata, or prior route events
- **THEN** none of those values appear in the entry or reconstructed response

#### Scenario: Unknown entry version is not replayed
- **WHEN** an entry has an unknown schema or key version
- **THEN** lookup reports corruption or incompatibility, best-effort deletes the entry, and continues as a miss

### Requirement: The write owner revalidates the current output contract
Before any cache write, framework-owned deterministic validation SHALL evaluate the response against the current request's `response_format`, `output_schema`, and `output_schema_name`. It MUST NOT trust provider-client metadata as proof. A response with tool calls, invalid structured output, unsupported content, or unsafe serialization SHALL NOT be written.

#### Scenario: Generic client returns invalid structured output
- **WHEN** a client claims success but its structured output violates the current request schema
- **THEN** the shared validator rejects the response according to the existing schema-error contract and no cache entry is written

#### Scenario: Client metadata cannot self-authorize a write
- **WHEN** response metadata states that structured output was validated but deterministic validation fails
- **THEN** the cache write is refused

#### Scenario: Tool call response is refused
- **WHEN** an otherwise eligible provider response contains any tool call
- **THEN** the response is returned or rejected according to the existing route contract but is never cached or replayed

### Requirement: Lookup outcomes are explicit and fail open
`LLMCacheStore.get` SHALL return a typed outcome distinguishing `hit`, `miss`, `expired`, `corrupt`, and `backend_error`. Corrupt or unverifiable entries MUST be treated as misses and deleted best-effort. Runtime backend errors SHALL emit diagnostic evidence and continue through the provider path without returning stale or untrusted data.

#### Scenario: Expired entry
- **WHEN** an entry is older than its finite TTL
- **THEN** lookup returns `expired`, removes it best-effort, and the router follows the normal miss path

#### Scenario: Corrupt entry
- **WHEN** entry decoding, integrity, schema, identity, or response validation fails
- **THEN** lookup returns `corrupt`, never returns a response, and the router follows the provider path

#### Scenario: Backend unavailable
- **WHEN** the cache backend times out or is unavailable at runtime
- **THEN** lookup returns `backend_error` and the provider path remains governed by the existing cooldown and budget rules

### Requirement: In-memory storage is bounded, isolated, and thread-safe
`InMemoryLLMCache` SHALL provide finite validated entry limits, optional finite byte limits, monotonic TTL handling, LRU eviction, synchronized get/put/delete and lease operations, and object isolation through deep copy or serialization round trip. It SHALL expose the same store and owner-token lease contracts as production adapters.

#### Scenario: LRU capacity eviction
- **WHEN** adding an entry exceeds `max_entries` or `max_bytes`
- **THEN** least-recently-used eligible entries are evicted until both limits are satisfied

#### Scenario: Concurrent access preserves invariants
- **WHEN** multiple threads read, write, expire, and evict entries concurrently
- **THEN** no partial value is observed and configured bounds remain satisfied

#### Scenario: Returned values cannot mutate storage
- **WHEN** a caller mutates a response obtained from the memory cache
- **THEN** a subsequent read returns the original isolated entry

#### Scenario: Invalid bounds fail at construction
- **WHEN** memory-cache limits or default TTL are non-finite, non-positive, or inconsistent
- **THEN** construction fails with a configuration error

### Requirement: Entry size and TTL are bounded
Every production write SHALL use a finite positive TTL and SHALL measure the encoded entry against `max_entry_bytes` before storage. An oversized response SHALL still be returned to the caller when otherwise valid, but MUST NOT be cached.

#### Scenario: Entry exceeds maximum size
- **WHEN** the encoded safe entry is larger than `max_entry_bytes`
- **THEN** the provider response is returned, the write result is `entry_too_large`, and no value is stored

#### Scenario: Production write has no TTL
- **WHEN** production composition attempts a write without a finite positive TTL
- **THEN** configuration or write validation rejects it before backend storage

### Requirement: Invalidation is generation-based and bounded
Prompt, model, provider, route, schema, dependency, visibility, codec, redaction, or policy-semantic changes SHALL change a generation, key version, dependency fingerprint, or namespace so stale entries no longer match. Request paths MUST NOT perform unbounded scans or deletes.

#### Scenario: Generation bump invalidates prior entries
- **WHEN** operators bump cache generation after a prompt or policy change
- **THEN** new requests miss old entries without scanning the backend

#### Scenario: Cache rollback preserves provider operation
- **WHEN** caching is disabled or the cache namespace is replaced
- **THEN** existing provider routing continues and disposable old entries do not affect durable state
