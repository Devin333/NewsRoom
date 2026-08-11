from __future__ import annotations

import math
import secrets
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, overload

from framework.llm.cache.contracts import (
    CacheLookup,
    CacheLookupStatus,
    CacheWriteResult,
    CacheWriteStatus,
    SingleFlightAcquireResult,
    SingleFlightAcquireStatus,
    SingleFlightLease,
    SingleFlightReleaseResult,
)
from framework.llm.cache.entry import CacheEntry, CacheResponseValidationError
from framework.llm.cache.key import LLMCacheKey
from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse


Clock = Callable[[], float]
_UNSET = object()


@dataclass(frozen=True)
class _StoredEntry:
    entry: CacheEntry
    stored_at: float
    expires_at: float | None
    size_bytes: int


@dataclass(frozen=True)
class _StoredLease:
    owner_token: str
    expires_at: float


class InMemoryLLMCache:
    backend_name = "memory"

    def __init__(
        self,
        *,
        max_entries: int = 1_024,
        max_bytes: int | None = 64 * 1024 * 1024,
        default_ttl_seconds: float | None = 300.0,
        clock: Clock | None = None,
        wall_clock: Clock | None = None,
    ) -> None:
        if isinstance(max_entries, bool) or int(max_entries) <= 0:
            raise ValueError("max_entries must be greater than zero")
        if max_bytes is not None and (
            isinstance(max_bytes, bool) or int(max_bytes) <= 0
        ):
            raise ValueError("max_bytes must be greater than zero")
        _validate_optional_ttl(default_ttl_seconds, field="default_ttl_seconds")
        self.max_entries = int(max_entries)
        self.max_bytes = int(max_bytes) if max_bytes is not None else None
        self.default_ttl_seconds = (
            float(default_ttl_seconds) if default_ttl_seconds is not None else None
        )
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._entries: OrderedDict[str, _StoredEntry] = OrderedDict()
        self._leases: dict[str, _StoredLease] = {}
        self._total_bytes = 0
        self._lock = threading.RLock()

    @overload
    def get(self, key: LLMCacheKey) -> CacheLookup: ...

    @overload
    def get(
        self,
        key: LLMCacheKey,
        *,
        ttl_seconds: float | None,
    ) -> LLMResponse | None: ...

    def get(
        self,
        key: LLMCacheKey,
        *,
        ttl_seconds: float | None | object = _UNSET,
    ) -> CacheLookup | LLMResponse | None:
        lookup = self._lookup(key)
        if ttl_seconds is _UNSET:
            return lookup
        _validate_optional_ttl(ttl_seconds, field="ttl_seconds")
        if not lookup.hit or lookup.entry is None:
            return None
        if ttl_seconds is not None and (lookup.age_seconds or 0.0) > float(ttl_seconds):
            self.delete(key)
            return None
        return deepcopy(lookup.entry.to_response())

    def _lookup(self, key: LLMCacheKey) -> CacheLookup:
        cache_key = key.to_string()
        with self._lock:
            now = self._clock()
            stored = self._entries.get(cache_key)
            if stored is None:
                return CacheLookup(status=CacheLookupStatus.MISS, backend=self.backend_name)
            if stored.expires_at is not None and stored.expires_at <= now:
                self._remove_entry(cache_key)
                return CacheLookup(status=CacheLookupStatus.EXPIRED, backend=self.backend_name)
            try:
                stored.entry.validate_identity(key)
                entry = CacheEntry.from_dict(deepcopy(stored.entry.to_dict()))
            except (CacheResponseValidationError, TypeError, ValueError):
                self._remove_entry(cache_key)
                return CacheLookup(
                    status=CacheLookupStatus.CORRUPT,
                    reason="entry_validation_failed",
                    backend=self.backend_name,
                )
            self._entries.move_to_end(cache_key)
            return CacheLookup.hit_entry(
                entry,
                age_seconds=max(0.0, now - stored.stored_at),
                backend=self.backend_name,
            )

    def put(
        self,
        key: LLMCacheKey,
        entry: CacheEntry,
        *,
        ttl_seconds: float,
    ) -> CacheWriteResult:
        ttl = _validate_required_ttl(ttl_seconds, field="ttl_seconds")
        try:
            entry.validate_identity(key)
            isolated = CacheEntry.from_dict(deepcopy(entry.to_dict()))
            size_bytes = len(isolated.to_json_bytes())
        except (CacheResponseValidationError, TypeError, ValueError) as exc:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason=type(exc).__name__,
                backend=self.backend_name,
            )
        if self.max_bytes is not None and size_bytes > self.max_bytes:
            return CacheWriteResult(
                status=CacheWriteStatus.ENTRY_TOO_LARGE,
                reason="entry_too_large",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )

        cache_key = key.to_string()
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            self._remove_entry(cache_key)
            self._entries[cache_key] = _StoredEntry(
                entry=isolated,
                stored_at=now,
                expires_at=now + ttl,
                size_bytes=size_bytes,
            )
            self._total_bytes += size_bytes
            self._evict_to_bounds()
            stored = cache_key in self._entries
        if not stored:
            return CacheWriteResult(
                status=CacheWriteStatus.ENTRY_TOO_LARGE,
                reason="entry_evicted_by_capacity",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        return CacheWriteResult(
            status=CacheWriteStatus.WRITTEN,
            size_bytes=size_bytes,
            backend=self.backend_name,
        )

    def set(self, key: LLMCacheKey, response: LLMResponse) -> None:
        """Compatibility write used only by `CachedLLMClient` tests/development."""
        request = LLMRequest(messages=[], temperature=0)
        entry = CacheEntry.from_response(
            key=key,
            request=request,
            response=response,
            created_at=self._wall_clock(),
        )
        ttl = self.default_ttl_seconds
        if ttl is None:
            ttl = float(10 * 365 * 24 * 60 * 60)
        self.put(key, entry, ttl_seconds=ttl)

    def delete(self, key: LLMCacheKey) -> bool:
        with self._lock:
            return self._remove_entry(key.to_string())

    def acquire_singleflight(
        self,
        key: LLMCacheKey,
        *,
        owner_token: str,
        ttl_seconds: float,
    ) -> SingleFlightAcquireResult:
        token = _required_owner_token(owner_token)
        ttl = _validate_required_ttl(ttl_seconds, field="ttl_seconds")
        cache_key = key.to_string()
        with self._lock:
            now = self._clock()
            existing = self._leases.get(cache_key)
            if existing is not None and existing.expires_at <= now:
                self._leases.pop(cache_key, None)
                existing = None
            if existing is not None:
                return SingleFlightAcquireResult(status=SingleFlightAcquireStatus.BUSY)
            expires_at = now + ttl
            self._leases[cache_key] = _StoredLease(
                owner_token=token,
                expires_at=expires_at,
            )
            return SingleFlightAcquireResult(
                status=SingleFlightAcquireStatus.ACQUIRED,
                lease=SingleFlightLease(
                    cache_key=cache_key,
                    owner_token=token,
                    expires_at_monotonic=expires_at,
                ),
            )

    def release_singleflight(self, lease: SingleFlightLease) -> SingleFlightReleaseResult:
        with self._lock:
            current = self._leases.get(lease.cache_key)
            if current is None or current.owner_token != lease.owner_token:
                return SingleFlightReleaseResult(released=False, reason="not_owner")
            self._leases.pop(lease.cache_key, None)
            return SingleFlightReleaseResult(released=True)

    def new_owner_token(self) -> str:
        return secrets.token_urlsafe(24)

    @property
    def entry_count(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._entries)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return self._total_bytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._leases.clear()
            self._total_bytes = 0

    def _purge_expired(self, now: float) -> None:
        expired = [
            cache_key
            for cache_key, stored in self._entries.items()
            if stored.expires_at is not None and stored.expires_at <= now
        ]
        for cache_key in expired:
            self._remove_entry(cache_key)
        expired_leases = [
            cache_key
            for cache_key, lease in self._leases.items()
            if lease.expires_at <= now
        ]
        for cache_key in expired_leases:
            self._leases.pop(cache_key, None)

    def _evict_to_bounds(self) -> None:
        while len(self._entries) > self.max_entries or (
            self.max_bytes is not None and self._total_bytes > self.max_bytes
        ):
            _, stored = self._entries.popitem(last=False)
            self._total_bytes -= stored.size_bytes

    def _remove_entry(self, cache_key: str) -> bool:
        stored = self._entries.pop(cache_key, None)
        if stored is None:
            return False
        self._total_bytes -= stored.size_bytes
        return True


def _validate_optional_ttl(value: float | None | object, *, field: str) -> float | None:
    if value is None:
        return None
    if value is _UNSET:
        return None
    return _validate_required_ttl(value, field=field)


def _validate_required_ttl(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return parsed


def _required_owner_token(value: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 8:
        raise ValueError("owner_token must contain at least 8 characters")
    return value.strip()
