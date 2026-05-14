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
        self.set(pointer.key, pointer.value, ttl_seconds=pointer.ttl_seconds)

    def get_pointer(self, key: str) -> dict[str, Any] | None:
        payload = self.get(key)
        return payload if isinstance(payload, dict) else None

    def delete_pointer(self, key: str) -> None:
        self.delete(key)

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if ttl_seconds is None:
            self.redis.set(self._key(key), payload)
        else:
            self.redis.set(self._key(key), payload, ex=ttl_seconds)

    def get(self, key: str) -> Any | None:
        raw = self.redis.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(str(raw))

    def delete(self, key: str) -> None:
        self.redis.delete(self._key(key))

    def expire(self, key: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        return bool(self.redis.expire(self._key(key), ttl_seconds))

    def list_keys(self, pattern: str = "*") -> list[str]:
        _validate_runtime_key_pattern(pattern)
        prefix = f"{self.key_prefix}:"
        raw_keys = self.redis.keys(f"{prefix}{pattern}")
        keys = [key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in raw_keys]
        return sorted(key.removeprefix(prefix) for key in keys if key.startswith(prefix))

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
        self.set(pointer.key, pointer.value, ttl_seconds=pointer.ttl_seconds)

    def get_pointer(self, key: str) -> dict[str, Any] | None:
        value = self.get(key)
        return value if isinstance(value, dict) else None

    def delete_pointer(self, key: str) -> None:
        self.delete(key)

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        _validate_runtime_key(key)
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        self._values[key] = (
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            expires_at,
        )

    def get(self, key: str) -> Any | None:
        _validate_runtime_key(key)
        value = self._values.get(key)
        if value is None:
            return None
        payload, expires_at = value
        if expires_at is not None and expires_at <= time.time():
            self._values.pop(key, None)
            return None
        return json.loads(payload)

    def delete(self, key: str) -> None:
        _validate_runtime_key(key)
        self._values.pop(key, None)

    def expire(self, key: str, ttl_seconds: int) -> bool:
        _validate_runtime_key(key)
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        value = self._values.get(key)
        if value is None or self.get(key) is None:
            return False
        payload, _ = self._values[key]
        self._values[key] = (payload, time.time() + ttl_seconds)
        return True

    def list_keys(self, pattern: str = "*") -> list[str]:
        _validate_runtime_key_pattern(pattern)
        _ = [self.get(key) for key in list(self._values)]
        if pattern == "*":
            return sorted(self._values)
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return sorted(key for key in self._values if key.startswith(prefix))
        return sorted(key for key in self._values if key == pattern)

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


def _validate_runtime_key(value: str) -> None:
    if not value or "/" in value or ".." in value:
        raise ValueError(f"invalid runtime key: {value}")


def _validate_runtime_key_pattern(value: str) -> None:
    if not value or "/" in value or ".." in value:
        raise ValueError(f"invalid runtime key pattern: {value}")
