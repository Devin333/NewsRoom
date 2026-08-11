# LLM Response Cache Operations

The LLM response cache is a disposable optimization owned by `LLMRouter`.
Harness remains the control plane: a cache hit does not decide routing, quality,
publication, memory writes, tool authorization, or any `VERIFY` result. Provider
clients remain ordinary `LLMClient` instances and must not wrap themselves in a
second production cache.

## Rollout and rollback

Use the modes in this order:

```text
disabled -> observe -> write_only -> read_write
```

- `disabled` constructs no cache backend and resolves no cache secrets.
- `observe` evaluates eligibility and keyability without Redis reads or writes.
- `write_only` populates accepted complete responses without serving hits.
- `read_write` serves exact entries for the audited task allowlist.

Rollback is `NEWS_LLM_CACHE_MODE=disabled`. Redis loss, restart, eviction, or
flush must only reduce hit rate; it must never prevent workflow replay or alter
durable reports, events, artifacts, evidence, queues, or pointers.

## Redis isolation

Production uses `NEWS_LLM_CACHE_REDIS_URL`, never `NEWS_REDIS_URL`. Use a
dedicated Redis instance or cluster with `rediss://`, a cache-only ACL identity,
and a cache-only eviction policy such as `allkeys-lfu`. Do not colocate disposable
cache values with durable runtime data under an eviction policy.

The default key prefix is `newsroom:llm-cache:*`. A minimal ACL needs connectivity
plus exact-prefix `GET`, `SET`, `DEL`, `PTTL`, and compare-and-delete `EVAL`
operations. It does not need `KEYS`, global `SCAN`, runtime-store, worker queue,
event, artifact, or business-fact access. Keep the password in the deployment
secret manager and place the dedicated ACL username/password in the redacted
`rediss://` connection secret.

All entries have a finite atomic expiry. Values are AES-256-GCM envelopes using
`NEWS_LLM_CACHE_ENCRYPTION_KEY`; associated data binds the namespace, external
HMAC key, and entry schema. `NEWS_LLM_CACHE_KEY_SECRET` is separate HMAC material.
Never reuse activity/event encryption keys or commit either value.

Generate the encryption setting as URL-safe base64 for 32 random bytes. Rotate
the HMAC and encryption secrets together with a generation, key-version, or
namespace bump; old entries are disposable misses and do not need migration.

## Configuration gates

`LLMCacheSettings` rejects startup when any enabled Redis configuration has:

- a missing dedicated URL or secret;
- insecure non-local transport or a production URL without a dedicated ACL user;
- a reserved/overlapping namespace;
- an invalid TTL, entry-size, connect/socket timeout, wait, or poll bound;
- a lock TTL that does not exceed provider timeout plus its safety margin;
- reused HMAC/encryption material; or
- an unknown mode, backend, or task-policy field.

The task allowlist defaults to empty. Use either
`NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES` with global required dependencies or
`NEWS_LLM_CACHE_TASK_POLICIES_JSON` with strict per-task dependency lists. Do not
enable live/freshness-sensitive or tool-bearing work.

## Readiness and diagnostics

Call `RedisLLMCache.readiness()` from an operator-controlled health path. The
probe uses random, short-lived exact keys under the configured cache prefix and
checks `PING`, `SET`, `GET`, `DEL`, and atomic lease release. It never scans keys,
reads another namespace, or stores request/response content.

Treat `available=false` as a cache degradation. Requests continue through the
normal cooldown, budget, provider, fallback, and Harness verification gates.
Investigate TLS, ACL, timeout, capacity, and Redis health without changing the
provider error returned to callers.

Router evidence exposes only mode, deployment identity, stable reason codes,
bounded timing/size data, key version, and a short HMAC digest prefix. It must not
contain prompts, responses, tool arguments, raw scope identifiers, full keys, or
secrets.

## Invalidation and incident response

Do not scan or synchronously delete the cache from request paths. Invalidate by
changing one of:

- `NEWS_LLM_CACHE_GENERATION` for prompt, policy, retrieval, permission, or model
  semantic changes;
- `NEWS_LLM_CACHE_KEY_VERSION` for canonicalization/key format changes; or
- `NEWS_LLM_CACHE_NAMESPACE` for an isolated security or operational reset.

For a suspected secret or payload incident:

1. Set mode to `disabled`.
2. Revoke the cache ACL and rotate both cache-specific secrets.
3. Bump namespace/key version/generation before re-enabling.
4. Review durable Harness/router evidence; do not treat Redis itself as an audit
   store.
5. Restore through `observe`, then `write_only`, then an audited `read_write`
   allowlist.

## Verification

The default suite uses an in-process fake and requires no Redis service:

```powershell
python -m pytest tests/infrastructure/storage/test_redis_llm_cache.py tests/interfaces/composition/test_llm_cache_settings.py -q
```

The real Redis test is opt-in and must target a disposable, dedicated test URL:

```powershell
$env:NEWS_LLM_CACHE_REAL_REDIS_TESTS = "1"
$env:NEWS_TEST_LLM_CACHE_REDIS_URL = "redis://127.0.0.1:6379/15"
python -m pytest tests/infrastructure/storage/test_redis_llm_cache.py -m redis_integration -q
```

The test uses a unique namespace and exact-key cleanup only.
