from storage.redis_runtime import InMemoryRuntimeStore, RedisRuntimeStore, RuntimePointer


def test_in_memory_runtime_store_saves_pointer_and_lock() -> None:
    store = InMemoryRuntimeStore()

    store.set_pointer(RuntimePointer("active-run", {"run_id": "run-1"}, ttl_seconds=60))

    assert store.get_pointer("active-run") == {"run_id": "run-1"}
    assert store.acquire_lock("run-1", owner="worker-1", ttl_seconds=60) is True
    assert store.acquire_lock("run-1", owner="worker-2", ttl_seconds=60) is False
    assert store.release_lock("run-1", owner="worker-2") is False
    assert store.release_lock("run-1", owner="worker-1") is True


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
