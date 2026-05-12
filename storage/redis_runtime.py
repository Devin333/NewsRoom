from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


@dataclass(frozen=True)
class RuntimePointer:
    key: str
    value: dict[str, Any]
    ttl_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": dict(self.value),
            "ttl_seconds": self.ttl_seconds,
        }


class RedisRuntimeStore:
    def __init__(self, redis_client: Any, *, key_prefix: str = "news:runtime") -> None:
        self.redis = redis_client
        self.key_prefix = key_prefix.rstrip(":")

    def set_pointer(self, pointer: RuntimePointer) -> None:
        key = self._key(pointer.key)
        payload = json.dumps(pointer.value, ensure_ascii=False, sort_keys=True)
        if pointer.ttl_seconds is None:
            self.redis.set(key, payload)
        else:
            self.redis.set(key, payload, ex=pointer.ttl_seconds)

    def get_pointer(self, key: str) -> dict[str, Any] | None:
        raw = self.redis.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(str(raw))
        return payload if isinstance(payload, dict) else None

    def delete_pointer(self, key: str) -> None:
        self.redis.delete(self._key(key))

    def acquire_lock(self, key: str, *, owner: str, ttl_seconds: int) -> bool:
        return bool(self.redis.set(self._key(f"lock:{key}"), owner, nx=True, ex=ttl_seconds))

    def release_lock(self, key: str, *, owner: str) -> bool:
        lock_key = self._key(f"lock:{key}")
        current = self.redis.get(lock_key)
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current != owner:
            return False
        self.redis.delete(lock_key)
        return True

    def _key(self, key: str) -> str:
        if not key or "/" in key or ".." in key:
            raise ValueError(f"invalid runtime key: {key}")
        return f"{self.key_prefix}:{key}"


class InMemoryRuntimeStore:
    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}

    def set_pointer(self, pointer: RuntimePointer) -> None:
        expires_at = time.time() + pointer.ttl_seconds if pointer.ttl_seconds is not None else None
        self._values[pointer.key] = (
            json.dumps(pointer.value, ensure_ascii=False, sort_keys=True),
            expires_at,
        )

    def get_pointer(self, key: str) -> dict[str, Any] | None:
        value = self._values.get(key)
        if value is None:
            return None
        payload, expires_at = value
        if expires_at is not None and expires_at <= time.time():
            self._values.pop(key, None)
            return None
        decoded = json.loads(payload)
        return decoded if isinstance(decoded, dict) else None

    def delete_pointer(self, key: str) -> None:
        self._values.pop(key, None)

    def acquire_lock(self, key: str, *, owner: str, ttl_seconds: int) -> bool:
        lock_key = f"lock:{key}"
        if self.get_pointer(lock_key) is not None:
            return False
        self.set_pointer(RuntimePointer(lock_key, {"owner": owner}, ttl_seconds=ttl_seconds))
        return True

    def release_lock(self, key: str, *, owner: str) -> bool:
        lock_key = f"lock:{key}"
        current = self.get_pointer(lock_key)
        if not current or current.get("owner") != owner:
            return False
        self.delete_pointer(lock_key)
        return True


def redis_runtime_store_from_env(
    *,
    env: dict[str, str] | None = None,
    redis_client: Any | None = None,
) -> RedisRuntimeStore:
    if redis_client is not None:
        return RedisRuntimeStore(redis_client)
    import os
    import redis

    values = env if env is not None else os.environ
    url = values.get("NEWS_REDIS_URL", DEFAULT_REDIS_URL)
    return RedisRuntimeStore(redis.from_url(url, decode_responses=True))
