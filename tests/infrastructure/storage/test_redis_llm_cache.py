from __future__ import annotations

import base64
import os
from dataclasses import replace
from uuid import uuid4

import pytest

from framework.llm.cache import (
    CacheContext,
    CacheDependencies,
    CacheEntry,
    CacheLookupStatus,
    CacheScope,
    CacheWriteStatus,
    LLMCacheKey,
    LLMCacheKeyFactory,
)
from framework.llm.models import LLMRequest, LLMResponse, TokenUsage
from infrastructure.storage.redis_llm_cache import (
    LLMCacheEnvelopeCodec,
    RedisLLMCache,
    decode_llm_cache_encryption_key,
    validate_llm_cache_namespace,
)


_NAMESPACE = "newsroom:llm-cache:test"
_ENCRYPTION_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
_OTHER_ENCRYPTION_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expiries_ms: dict[str, float] = {}
        self.now_ms = 10_000.0
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.fail_operations: set[str] = set()

    def set(self, key, value, **kwargs):  # type: ignore[no-untyped-def]
        self._fail("set")
        self._purge(str(key))
        self.calls.append(("set", (key, value), dict(kwargs)))
        if kwargs.get("nx") and str(key) in self.values:
            return False
        self.values[str(key)] = value
        if kwargs.get("px") is not None:
            self.expiries_ms[str(key)] = self.now_ms + float(kwargs["px"])
        elif kwargs.get("ex") is not None:
            self.expiries_ms[str(key)] = self.now_ms + float(kwargs["ex"]) * 1_000
        else:
            self.expiries_ms.pop(str(key), None)
        return True

    def get(self, key):  # type: ignore[no-untyped-def]
        self._fail("get")
        self._purge(str(key))
        self.calls.append(("get", (key,), {}))
        return self.values.get(str(key))

    def pttl(self, key):  # type: ignore[no-untyped-def]
        self._fail("pttl")
        self._purge(str(key))
        self.calls.append(("pttl", (key,), {}))
        if str(key) not in self.values:
            return -2
        expiry = self.expiries_ms.get(str(key))
        if expiry is None:
            return -1
        return max(0, int(expiry - self.now_ms))

    def delete(self, key):  # type: ignore[no-untyped-def]
        self._fail("delete")
        self.calls.append(("delete", (key,), {}))
        existed = str(key) in self.values
        self.values.pop(str(key), None)
        self.expiries_ms.pop(str(key), None)
        return int(existed)

    def eval(self, script, numkeys, *args):  # type: ignore[no-untyped-def]
        self._fail("eval")
        self.calls.append(("eval", (script, numkeys, *args), {}))
        assert numkeys == 1
        key, owner = str(args[0]), args[1]
        self._purge(key)
        current = self.values.get(key)
        if isinstance(current, bytes) and isinstance(owner, str):
            current = current.decode("utf-8")
        if current != owner:
            return 0
        self.values.pop(key, None)
        self.expiries_ms.pop(key, None)
        return 1

    def ping(self):  # type: ignore[no-untyped-def]
        self._fail("ping")
        self.calls.append(("ping", (), {}))
        return True

    def advance(self, milliseconds: float) -> None:
        self.now_ms += milliseconds

    def _purge(self, key: str) -> None:
        expiry = self.expiries_ms.get(key)
        if expiry is not None and expiry <= self.now_ms:
            self.values.pop(key, None)
            self.expiries_ms.pop(key, None)

    def _fail(self, operation: str) -> None:
        if operation in self.fail_operations:
            raise TimeoutError(f"{operation} secret backend detail")


def _request(content: str = "prompt that must not be stored") -> LLMRequest:
    return LLMRequest(
        messages=[{"role": "user", "content": content}],
        temperature=0,
        metadata={"task_type": "classify"},
    )


def _key(
    request: LLMRequest | None = None,
    *,
    model: str = "model-a",
    key_version: str = "v1",
) -> LLMCacheKey:
    return LLMCacheKeyFactory(
        secret="separate-hmac-secret-material",
        namespace=_NAMESPACE,
        key_version=key_version,
        cache_generation="generation-a",
    ).build(
        request=request or _request(),
        context=CacheContext(
            scope=CacheScope("tenant-sensitive", "project-sensitive", "policy-sensitive"),
            dependencies=CacheDependencies({"prompt_revision": "revision-a"}),
        ),
        deployment_id="deployment-a",
        provider="provider-a",
        model=model,
    )


def _entry(key: LLMCacheKey, content: str = "response that must be encrypted") -> CacheEntry:
    return CacheEntry.from_response(
        key=key,
        request=_request(),
        response=LLMResponse(
            content=content,
            usage=TokenUsage(input_tokens=4, output_tokens=3),
            metadata={"finish_reason": "stop", "run_id": "must-not-persist"},
            raw={"authorization": "must-not-persist"},
        ),
        created_at=1_000.0,
    )


def _store(
    redis: FakeRedis,
    *,
    encryption_key: str = _ENCRYPTION_KEY,
    max_entry_bytes: int = 1_048_576,
) -> RedisLLMCache:
    return RedisLLMCache(
        redis,
        namespace=_NAMESPACE,
        codec=LLMCacheEnvelopeCodec(
            namespace=_NAMESPACE,
            encryption_key=encryption_key,
        ),
        max_entry_bytes=max_entry_bytes,
        max_ttl_seconds=600,
        max_lease_ttl_seconds=120,
        monotonic_clock=lambda: redis.now_ms / 1_000,
        wall_clock=lambda: 1_030.0,
    )


def test_encrypted_round_trip_uses_one_expiring_write_and_stores_no_plaintext() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()

    written = store.put(key, _entry(key), ttl_seconds=60)
    lookup = store.get(key)

    assert written.status is CacheWriteStatus.WRITTEN
    assert lookup.status is CacheLookupStatus.HIT
    assert lookup.entry is not None
    assert lookup.entry.to_response().content == "response that must be encrypted"
    assert lookup.age_seconds == 30.0
    external_key = key.to_string()
    raw = redis.values[external_key]
    assert isinstance(raw, bytes)
    for forbidden in (
        b"response that must be encrypted",
        b"prompt that must not be stored",
        b"tenant-sensitive",
        b"separate-hmac-secret-material",
        b"must-not-persist",
    ):
        assert forbidden not in raw
    entry_sets = [call for call in redis.calls if call[0] == "set"]
    assert entry_sets == [("set", (external_key, raw), {"ex": 60})]


def test_string_redis_value_is_accepted_for_ascii_envelope() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    assert store.put(key, _entry(key), ttl_seconds=60).stored
    redis.values[key.to_string()] = bytes(redis.values[key.to_string()]).decode("ascii")

    assert store.get(key).status is CacheLookupStatus.HIT


@pytest.mark.parametrize("mutation", ["ciphertext", "nonce", "version", "json"])
def test_tampered_envelope_is_corrupt_and_deleted(mutation: str) -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    assert store.put(key, _entry(key), ttl_seconds=60).stored
    external_key = key.to_string()
    raw = bytes(redis.values[external_key])
    if mutation == "json":
        redis.values[external_key] = b"not-json"
    elif mutation == "version":
        redis.values[external_key] = raw.replace(
            b"newsroom.llm-cache-envelope.v1",
            b"newsroom.llm-cache-envelope.v0",
        )
    else:
        marker = b'"ciphertext":"' if mutation == "ciphertext" else b'"nonce":"'
        position = raw.index(marker) + len(marker)
        replacement = b"A" if raw[position : position + 1] != b"A" else b"B"
        redis.values[external_key] = raw[:position] + replacement + raw[position + 1 :]

    lookup = store.get(key)

    assert lookup.status is CacheLookupStatus.CORRUPT
    assert lookup.reason == "encrypted_entry_validation_failed"
    assert external_key not in redis.values


def test_wrong_encryption_key_and_wrong_aad_key_are_never_replayed() -> None:
    redis = FakeRedis()
    writer = _store(redis)
    source_key = _key()
    assert writer.put(source_key, _entry(source_key), ttl_seconds=60).stored
    external_key = source_key.to_string()
    encrypted = redis.values[external_key]
    expiry = redis.expiries_ms[external_key]

    wrong_key_reader = _store(redis, encryption_key=_OTHER_ENCRYPTION_KEY)
    assert wrong_key_reader.get(source_key).status is CacheLookupStatus.CORRUPT

    target_key = _key(model="model-b")
    redis.values[target_key.to_string()] = encrypted
    redis.expiries_ms[target_key.to_string()] = expiry
    assert writer.get(target_key).status is CacheLookupStatus.CORRUPT
    assert target_key.to_string() not in redis.values


def test_oversized_write_and_read_are_rejected_before_decode_or_storage() -> None:
    redis = FakeRedis()
    key = _key()
    small_store = _store(redis, max_entry_bytes=200)

    written = small_store.put(key, _entry(key, content="x" * 200), ttl_seconds=60)

    assert written.status is CacheWriteStatus.ENTRY_TOO_LARGE
    assert not [call for call in redis.calls if call[0] == "set"]

    external_key = key.to_string()
    redis.values[external_key] = b"x" * 201
    redis.expiries_ms[external_key] = redis.now_ms + 60_000
    lookup = small_store.get(key)
    assert lookup.status is CacheLookupStatus.CORRUPT
    assert lookup.reason == "encoded_entry_too_large"
    assert external_key not in redis.values


def test_missing_expiry_is_corrupt_but_normal_expiry_is_a_miss() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    assert store.put(key, _entry(key), ttl_seconds=1).stored
    external_key = key.to_string()
    redis.expiries_ms.pop(external_key)

    assert store.get(key).reason == "entry_missing_expiry"
    assert external_key not in redis.values

    assert store.put(key, _entry(key), ttl_seconds=1).stored
    redis.advance(1_001)
    assert store.get(key).status is CacheLookupStatus.MISS


def test_runtime_backend_failures_return_typed_redacted_outcomes() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    redis.fail_operations.add("get")

    lookup = store.get(key)

    assert lookup.status is CacheLookupStatus.BACKEND_ERROR
    assert lookup.reason == "TimeoutError"
    assert "secret" not in repr(lookup)

    redis.fail_operations = {"set"}
    written = store.put(key, _entry(key), ttl_seconds=60)
    assert written.status is CacheWriteStatus.BACKEND_ERROR
    assert written.reason == "TimeoutError"
    assert "secret" not in repr(written)

    redis.fail_operations = {"delete"}
    assert store.delete(key) is False


def test_singleflight_is_atomic_and_stale_owner_cannot_delete_replacement() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    owner_one = "owner-token-00000001"
    owner_two = "owner-token-00000002"

    first = store.acquire_singleflight(key, owner_token=owner_one, ttl_seconds=2)
    busy = store.acquire_singleflight(key, owner_token=owner_two, ttl_seconds=2)
    assert first.acquired
    assert busy.status is busy.status.BUSY
    assert first.lease is not None

    redis.advance(2_001)
    replacement = store.acquire_singleflight(key, owner_token=owner_two, ttl_seconds=2)
    assert replacement.acquired
    assert replacement.lease is not None

    stale_release = store.release_singleflight(first.lease)
    assert stale_release.released is False
    assert stale_release.reason == "not_owner"
    assert redis.get(f"{key.to_string()}:lease") == owner_two

    current_release = store.release_singleflight(replacement.lease)
    assert current_release.released is True
    assert redis.get(f"{key.to_string()}:lease") is None
    assert [call for call in redis.calls if call[0] == "eval"]


def test_singleflight_backend_failures_are_typed() -> None:
    redis = FakeRedis()
    store = _store(redis)
    key = _key()
    redis.fail_operations.add("set")
    acquire = store.acquire_singleflight(
        key,
        owner_token="owner-token-00000001",
        ttl_seconds=2,
    )
    assert acquire.status is acquire.status.BACKEND_ERROR
    assert acquire.reason == "TimeoutError"

    redis.fail_operations.clear()
    acquired = store.acquire_singleflight(
        key,
        owner_token="owner-token-00000001",
        ttl_seconds=2,
    )
    assert acquired.lease is not None
    redis.fail_operations.add("eval")
    released = store.release_singleflight(acquired.lease)
    assert released.released is False
    assert released.backend_error is True
    assert released.reason == "TimeoutError"


def test_readiness_uses_only_bounded_prefix_operations_and_preserves_runtime_keys() -> None:
    redis = FakeRedis()
    redis.values["news:runtime:active-run"] = b"durable-runtime-value"
    store = _store(redis)

    readiness = store.readiness()

    assert readiness.available is True
    assert readiness.reason == "ready"
    assert redis.values == {"news:runtime:active-run": b"durable-runtime-value"}
    assert {call[0] for call in redis.calls} <= {
        "delete",
        "eval",
        "get",
        "ping",
        "pttl",
        "set",
    }


@pytest.mark.parametrize(
    "namespace",
    ["", "news", "news:runtime", "news:runtime:cache", "newsroom:events:cache", "bad/key"],
)
def test_namespace_validation_rejects_unbounded_or_reserved_prefixes(namespace: str) -> None:
    with pytest.raises(ValueError, match="namespace"):
        validate_llm_cache_namespace(namespace)


def test_codec_rejects_invalid_key_material_without_exposing_it() -> None:
    secret = "not-a-valid-encryption-key"
    with pytest.raises(ValueError, match="LLM cache encryption key") as raised:
        decode_llm_cache_encryption_key(secret)
    assert secret not in str(raised.value)


@pytest.mark.redis_integration
def test_real_redis_round_trip_and_stale_release_is_opt_in() -> None:
    if os.environ.get("NEWS_LLM_CACHE_REAL_REDIS_TESTS") != "1":
        pytest.skip("set NEWS_LLM_CACHE_REAL_REDIS_TESTS=1 for the isolated Redis test")
    url = os.environ.get("NEWS_TEST_LLM_CACHE_REDIS_URL")
    if not url:
        pytest.skip("NEWS_TEST_LLM_CACHE_REDIS_URL is required")
    redis = pytest.importorskip("redis")
    client = redis.from_url(url, decode_responses=False, socket_timeout=2)
    namespace = f"newsroom:llm-cache:test:{uuid4().hex}"
    encryption_key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    store = RedisLLMCache(
        client,
        namespace=namespace,
        codec=LLMCacheEnvelopeCodec(namespace=namespace, encryption_key=encryption_key),
        max_lease_ttl_seconds=5,
    )
    source_key = _key()
    key = replace(source_key, namespace=namespace)
    try:
        assert store.put(key, _entry(key), ttl_seconds=5).stored
        assert store.get(key).hit
        first = store.acquire_singleflight(
            key,
            owner_token="owner-token-00000001",
            ttl_seconds=1,
        )
        assert first.lease is not None
        import time

        time.sleep(1.1)
        second = store.acquire_singleflight(
            key,
            owner_token="owner-token-00000002",
            ttl_seconds=1,
        )
        assert second.lease is not None
        assert store.release_singleflight(first.lease).released is False
        assert store.release_singleflight(second.lease).released is True
    finally:
        store.delete(key)
