# llm-cache-redis-backend Specification

## Purpose
TBD - created by archiving change llm-cache-production-hardening. Update Purpose after archive.
## Requirements
### Requirement: Redis cache uses a dedicated infrastructure boundary
Production Redis caching SHALL use a dedicated `RedisLLMCache` adapter, URL, bounded namespace, credentials, and eviction domain. It MUST NOT reuse `RedisRuntimeStore` data keys, pointer/queue/event namespaces, optional-TTL semantics, non-atomic lock release, or key-scan operations.

#### Scenario: Cache eviction does not affect runtime state
- **WHEN** cache keys expire, are evicted, invalidated, or flushed within the cache namespace
- **THEN** runtime queues, locks, pointers, events, artifacts, and business facts remain unchanged

#### Scenario: Adapter never uses unbounded key scan
- **WHEN** cache lookup, invalidation, health probing, or cleanup executes
- **THEN** it addresses exact keys or bounded cursor operations and never invokes Redis `KEYS`

#### Scenario: Namespace is validated
- **WHEN** the configured cache namespace is empty, unbounded, overlaps a reserved runtime prefix, or contains unsupported characters
- **THEN** composition fails before creating the adapter

### Requirement: Redis payloads use cache-specific authenticated encryption
The Redis adapter SHALL protect each serialized entry with cache-specific AEAD using `NEWS_LLM_CACHE_ENCRYPTION_KEY`, with associated data binding the namespace, external key, and entry schema version. Key-identity HMAC and payload encryption MUST use distinct injected secrets. Plaintext responses, prompts, credentials, or scope identifiers MUST NOT be stored in Redis.

#### Scenario: Valid encrypted round trip
- **WHEN** an entry is written and read with the same keys, namespace, external key, and schema version
- **THEN** it decrypts, validates, and reconstructs the safe entry

#### Scenario: Payload tampering is rejected
- **WHEN** ciphertext, nonce, tag, associated data, or envelope bytes are modified
- **THEN** lookup returns `corrupt`, never exposes plaintext or a response, best-effort deletes the value, and records redacted evidence

#### Scenario: Wrong or rotated key invalidates entry
- **WHEN** an entry is read with a different encryption key, HMAC key version, or namespace
- **THEN** it cannot be replayed and is handled as an incompatible/corrupt miss

#### Scenario: Secrets are not serialized or logged
- **WHEN** codec, Redis, or configuration errors occur
- **THEN** neither encryption/HMAC material nor decrypted payload content appears in exceptions, logs, events, or metrics

### Requirement: Redis writes enforce finite TTL and encoded size
Every Redis value write SHALL use a finite validated TTL and SHALL reject encoded payloads larger than `max_entry_bytes` before network storage. The adapter SHALL use atomic set-with-expiry behavior so no successfully written cache entry can persist without expiration.

#### Scenario: Atomic expiring write
- **WHEN** a valid entry is stored
- **THEN** Redis receives a single bounded write operation with the required expiration

#### Scenario: Oversized encrypted envelope is refused
- **WHEN** serialization and encryption produce a payload larger than the configured maximum
- **THEN** the adapter returns `entry_too_large` and sends no value write

#### Scenario: Invalid TTL is rejected
- **WHEN** TTL is absent, non-finite, non-positive, or outside configured limits
- **THEN** startup or write validation fails before Redis mutation

### Requirement: Redis lookup validates every trust boundary
On read, the adapter SHALL validate Redis value type and size, outer envelope version, AEAD integrity, decoded schema, key/schema identity, source deployment identity, creation/expiry information, and safe response shape before returning a hit. Any unknown or invalid state MUST be a non-replayable outcome.

#### Scenario: Oversized stored value is rejected before decode
- **WHEN** Redis returns a value larger than the configured read bound
- **THEN** lookup reports corruption, does not allocate an unbounded decoder input, and best-effort deletes the key

#### Scenario: Entry identity does not match requested key
- **WHEN** a validly encrypted entry declares a different key version or source deployment identity
- **THEN** lookup treats it as corrupt/incompatible and never returns it

#### Scenario: Missing key is a normal miss
- **WHEN** Redis returns no value due to absence, expiry, eviction, restart, or flush
- **THEN** lookup returns `miss` without treating disposable cache loss as a durable-data failure

### Requirement: Redis runtime failures are bounded and fail open
Redis connect, read, write, delete, and lease operations SHALL use bounded connect/socket/operation timeouts. Runtime transient errors SHALL become typed backend outcomes so router logic can continue through existing provider gates. Startup configuration errors MUST fail fast rather than being silently downgraded.

#### Scenario: Lookup timeout
- **WHEN** Redis does not answer within the configured lookup timeout
- **THEN** the adapter returns `backend_error` promptly and the router may continue to the provider path

#### Scenario: Write timeout after provider success
- **WHEN** Redis write times out
- **THEN** the adapter reports write failure without changing the successful provider result

#### Scenario: Invalid production configuration
- **WHEN** required Redis URL, HMAC secret, encryption key, namespace, TTL, size, or timeout settings are invalid
- **THEN** non-disabled Redis composition fails at startup with a redacted configuration error

### Requirement: Redis transport and ACL settings are validated
Non-test Redis composition SHALL require TLS transport and a credential model intended for a cache-only ACL principal. The adapter SHALL expose a bounded readiness probe that verifies connectivity and exact-prefix permissions without writing sensitive content or enumerating unrelated keys.

#### Scenario: Insecure production URL is rejected
- **WHEN** a non-test production cache uses an unencrypted Redis URL without an explicit approved local/test override
- **THEN** startup validation fails

#### Scenario: Cache principal lacks required exact operations
- **WHEN** readiness cannot perform the bounded cache get/set/delete/lease operations in its namespace
- **THEN** readiness reports unavailable without accessing runtime namespaces

#### Scenario: ACL does not require global key access
- **WHEN** operator permissions are documented or validated
- **THEN** the cache principal only needs its dedicated prefix and does not require global scan or runtime-store permissions

### Requirement: Single-flight acquire is atomic and owner-token based
`acquire_singleflight` SHALL atomically create a finite lease only when absent and SHALL bind it to a caller-generated unguessable owner token. A failed acquire MUST return non-ownership without overwriting or extending the current owner's lease.

#### Scenario: One owner among concurrent contenders
- **WHEN** multiple workers atomically acquire the same missing key at the same time
- **THEN** exactly one receives ownership and all others receive a busy result

#### Scenario: Lease expires for recovery
- **WHEN** an owner terminates without release and the finite lease TTL elapses
- **THEN** a later worker can acquire a new lease with a new token

#### Scenario: Busy contender cannot renew owner lease
- **WHEN** a non-owner retries acquisition
- **THEN** it cannot replace the owner token or extend the existing expiration

### Requirement: Single-flight release is atomic compare-and-delete
`release_singleflight` SHALL execute an atomic owner-token comparison and deletion, such as a bounded Redis Lua script. It MUST NOT implement release as separate `GET` and unconditional `DEL` operations.

#### Scenario: Current owner releases lease
- **WHEN** the stored token equals the lease owner's token
- **THEN** the lock key is deleted atomically and release returns true

#### Scenario: Stale owner cannot delete replacement lease
- **WHEN** an old lease expires, a new owner acquires, and the old owner later calls release
- **THEN** the new lease remains intact and stale release returns false

#### Scenario: Release error is bounded
- **WHEN** Redis is unavailable during release
- **THEN** the operation returns a typed backend failure, relies on finite lease expiry for recovery, and never performs an unconditional delete

### Requirement: Single-flight waiting respects both configured and caller deadlines
The cache coordinator SHALL expose bounded recheck behavior using a positive polling interval and SHALL stop by the earlier of `singleflight_wait_timeout_ms` and the caller deadline. Configuration MUST ensure lock TTL exceeds provider timeout plus a safety margin.

#### Scenario: Entry appears during wait
- **WHEN** a waiter observes the owner-published exact entry before its deadline
- **THEN** it returns the hit and does not call the provider

#### Scenario: Caller deadline is shorter than wait timeout
- **WHEN** the caller deadline arrives first
- **THEN** waiting stops without sleeping past the deadline

#### Scenario: Invalid timeout relationship
- **WHEN** polling, wait, lease, provider, and safety-margin settings cannot satisfy bounded ownership
- **THEN** composition fails at startup

### Requirement: Redis cache configuration is typed and mode-aware
The runtime SHALL provide typed settings for mode, backend, namespace, key version, generation, TTL, maximum entry size, timeouts, single-flight, task policies, Redis URL reference, key-secret reference, and encryption-key reference. `disabled` mode SHALL not resolve Redis secrets or create a connection; all non-disabled Redis settings SHALL be validated before serving requests.

#### Scenario: Disabled mode has no infrastructure side effect
- **WHEN** cache mode is `disabled` and Redis environment variables are absent
- **THEN** application composition succeeds without a Redis client

#### Scenario: Non-disabled Redis mode requires secrets
- **WHEN** mode permits cache work and backend is Redis but URL or either secret is absent
- **THEN** composition fails with a redacted actionable configuration error

#### Scenario: Unsupported configuration key is rejected
- **WHEN** cache configuration contains an unknown mode, backend, field, or task-policy shape
- **THEN** the typed loader rejects it rather than ignoring dead configuration

### Requirement: Redis loss is disposable and restart-safe
Redis restart, failover, eviction, namespace rotation, or complete cache loss SHALL only reduce hit rate. Cache restoration MUST NOT be required for workflow replay, report integrity, event durability, or provider correctness.

#### Scenario: Empty cache after restart
- **WHEN** all cache entries and leases are lost during Redis restart
- **THEN** subsequent requests follow normal miss/provider paths and durable NewsRoom state remains replayable

#### Scenario: Stale lease is lost during failover
- **WHEN** a lease disappears before its owner finishes
- **THEN** duplicate provider work may occur within documented bounds, but no unvalidated response or cross-scope entry can be served
