import pytest

from infrastructure.storage.redis_runtime import InMemoryRuntimeStore, RedisRuntimeStore, RuntimePointer


def test_in_memory_runtime_store_saves_pointer_and_lock() -> None:
    store = InMemoryRuntimeStore()

    store.set_pointer(RuntimePointer("active-run", {"run_id": "run-1"}, ttl_seconds=60))

    assert store.get_pointer("active-run") == {"run_id": "run-1"}
    assert store.acquire_lock("run-1", owner="worker-1", ttl_seconds=60) is True
    assert store.acquire_lock("run-1", owner="worker-2", ttl_seconds=60) is False
    assert store.release_lock("run-1", owner="worker-2") is False
    assert store.release_lock("run-1", owner="worker-1") is True


def test_in_memory_runtime_store_supports_short_term_runtime_primitives() -> None:
    store = InMemoryRuntimeStore()

    store.set("progress:run-1", {"step": "draft"}, ttl_seconds=60)
    store.set("cache:source-1", ["item-1"])

    assert store.get("progress:run-1") == {"step": "draft"}
    assert store.get("cache:source-1") == ["item-1"]
    assert store.list_keys("progress:*") == ["progress:run-1"]
    assert store.list_keys() == ["cache:source-1", "progress:run-1"]
    assert store.expire("progress:run-1", 60) is True
    assert store.expire("missing", 60) is False

    store.delete("progress:run-1")

    assert store.get("progress:run-1") is None
    with pytest.raises(ValueError, match="invalid runtime key"):
        store.set("../report", {"should_not_store": True})
    with pytest.raises(ValueError, match="cannot persist long-term"):
        store.set("final_report:run-1", {"should_not_store": True})
    with pytest.raises(ValueError, match="cannot persist long-term"):
        store.get("evidence:ev-1")
    with pytest.raises(ValueError, match="ttl_seconds must be greater than zero"):
        store.expire("cache:source-1", 0)


def test_redis_runtime_store_uses_expiring_set_for_pointer_and_lock() -> None:
    redis = _FakeRedis()
    store = RedisRuntimeStore(redis, key_prefix="news:test")

    store.set_pointer(RuntimePointer("active-run", {"run_id": "run-1"}, ttl_seconds=30))
    acquired = store.acquire_lock("run-1", owner="worker-1", ttl_seconds=20)
    released = store.release_lock("run-1", owner="worker-1")

    assert redis.values["news:test:active-run"] == '{"run_id": "run-1"}'
    assert redis.expiries["news:test:active-run"] == 30
    assert acquired is True
    assert released is True
    assert "news:test:lock:run-1" not in redis.values


def test_redis_runtime_store_supports_short_term_runtime_primitives() -> None:
    redis = _FakeRedis()
    store = RedisRuntimeStore(redis, key_prefix="news:test")

    store.set("progress:run-1", {"step": "draft"}, ttl_seconds=30)
    store.set("cache:source-1", ["item-1"])

    assert store.get("progress:run-1") == {"step": "draft"}
    assert store.get("cache:source-1") == ["item-1"]
    assert store.list_keys("progress:*") == ["progress:run-1"]
    assert store.list_keys() == ["cache:source-1", "progress:run-1"]
    assert store.expire("progress:run-1", 10) is True
    assert redis.expiries["news:test:progress:run-1"] == 10

    store.delete("progress:run-1")

    assert store.get("progress:run-1") is None
    with pytest.raises(ValueError, match="invalid runtime key pattern"):
        store.list_keys("../*")
    with pytest.raises(ValueError, match="cannot persist long-term"):
        store.set("report:run-1", {"should_not_store": True})
    with pytest.raises(ValueError, match="cannot list long-term"):
        store.list_keys("evidence:*")


class _FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.expiries = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)
        self.expiries.pop(key, None)

    def expire(self, key, ex):
        if key not in self.values:
            return False
        self.expiries[key] = ex
        return True

    def keys(self, pattern):
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [key for key in self.values if key.startswith(prefix)]
        return [key for key in self.values if key == pattern]
