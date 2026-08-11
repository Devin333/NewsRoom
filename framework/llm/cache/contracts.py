from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Protocol

if TYPE_CHECKING:
    from framework.llm.cache.entry import CacheEntry
    from framework.llm.cache.key import LLMCacheKey
    from framework.llm.models.request import LLMRequest


class CacheMode(str, Enum):
    DISABLED = "disabled"
    OBSERVE = "observe"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"

    @property
    def reads(self) -> bool:
        return self is CacheMode.READ_WRITE

    @property
    def writes(self) -> bool:
        return self in {CacheMode.WRITE_ONLY, CacheMode.READ_WRITE}


@dataclass(frozen=True)
class CacheScope:
    tenant_id: str = field(repr=False)
    project_id: str = field(repr=False)
    policy_scope: str = field(repr=False)

    @property
    def complete(self) -> bool:
        return all(_non_empty_text(value) for value in self.values())

    def values(self) -> tuple[str, str, str]:
        return self.tenant_id, self.project_id, self.policy_scope

    def to_key_payload(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "policy_scope": self.policy_scope,
        }


@dataclass(frozen=True)
class CacheDependencies:
    values: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(deepcopy(dict(self.values))))

    def missing(self, required: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            name
            for name in required
            if name not in self.values or not _dependency_value_present(self.values[name])
        )

    def to_key_payload(self) -> dict[str, Any]:
        return dict(self.values)


@dataclass(frozen=True)
class CacheContext:
    scope: CacheScope | None = field(default=None, repr=False)
    dependencies: CacheDependencies = field(default_factory=CacheDependencies, repr=False)
    semantic_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    deterministic_seed: str | int | None = None
    freshness_sensitive: bool = False
    side_effect_candidate: bool = False
    deadline_monotonic: float | None = field(default=None, repr=False)
    malformed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "semantic_metadata",
            MappingProxyType(deepcopy(dict(self.semantic_metadata))),
        )

    @classmethod
    def from_request(cls, request: LLMRequest) -> CacheContext:
        metadata = dict(request.metadata)
        envelope = metadata.get("llm_cache")
        if not isinstance(envelope, Mapping):
            return cls(malformed=envelope is not None)

        malformed = False
        raw_scope = envelope.get("scope")
        scope: CacheScope | None = None
        if isinstance(raw_scope, Mapping):
            scope = CacheScope(
                tenant_id=_text_or_empty(raw_scope.get("tenant_id")),
                project_id=_text_or_empty(raw_scope.get("project_id")),
                policy_scope=_text_or_empty(raw_scope.get("policy_scope")),
            )
        elif raw_scope is not None:
            malformed = True

        raw_dependencies = envelope.get("dependencies", {})
        if not isinstance(raw_dependencies, Mapping):
            raw_dependencies = {}
            malformed = True

        raw_semantic = envelope.get("semantic", {})
        if not isinstance(raw_semantic, Mapping):
            raw_semantic = {}
            malformed = True

        seed = envelope.get("seed")
        if seed is not None and (
            isinstance(seed, bool) or not isinstance(seed, (str, int))
        ):
            seed = None
            malformed = True

        deadline = envelope.get("deadline_monotonic")
        parsed_deadline: float | None = None
        if deadline is not None:
            try:
                parsed_deadline = float(deadline)
            except (TypeError, ValueError):
                malformed = True
            else:
                if not math.isfinite(parsed_deadline) or parsed_deadline <= 0:
                    parsed_deadline = None
                    malformed = True

        freshness_sensitive = envelope.get("freshness_sensitive", False)
        if not isinstance(freshness_sensitive, bool):
            freshness_sensitive = False
            malformed = True
        side_effect_candidate = envelope.get("side_effect_candidate", False)
        if not isinstance(side_effect_candidate, bool):
            side_effect_candidate = False
            malformed = True

        return cls(
            scope=scope,
            dependencies=CacheDependencies(dict(raw_dependencies)),
            semantic_metadata=dict(raw_semantic),
            deterministic_seed=seed,
            freshness_sensitive=freshness_sensitive,
            side_effect_candidate=side_effect_candidate,
            deadline_monotonic=parsed_deadline,
            malformed=malformed,
        )


@dataclass(frozen=True)
class CacheEligibility:
    eligible: bool
    reason: str
    context: CacheContext | None = field(default=None, repr=False)


class CacheLookupStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"
    CORRUPT = "corrupt"
    BACKEND_ERROR = "backend_error"


@dataclass(frozen=True)
class CacheLookup:
    status: CacheLookupStatus
    entry: CacheEntry | None = None
    reason: str | None = None
    age_seconds: float | None = None
    backend: str = "unknown"

    @property
    def hit(self) -> bool:
        return self.status is CacheLookupStatus.HIT and self.entry is not None

    @classmethod
    def hit_entry(
        cls,
        entry: CacheEntry,
        *,
        age_seconds: float | None = None,
        backend: str,
    ) -> CacheLookup:
        return cls(
            status=CacheLookupStatus.HIT,
            entry=entry,
            age_seconds=age_seconds,
            backend=backend,
        )


class CacheWriteStatus(str, Enum):
    WRITTEN = "written"
    SKIPPED = "skipped"
    ENTRY_TOO_LARGE = "entry_too_large"
    BACKEND_ERROR = "backend_error"


@dataclass(frozen=True)
class CacheWriteResult:
    status: CacheWriteStatus
    reason: str | None = None
    size_bytes: int | None = None
    backend: str = "unknown"

    @property
    def stored(self) -> bool:
        return self.status is CacheWriteStatus.WRITTEN


@dataclass(frozen=True)
class SingleFlightLease:
    cache_key: str = field(repr=False)
    owner_token: str = field(repr=False)
    expires_at_monotonic: float


class SingleFlightAcquireStatus(str, Enum):
    ACQUIRED = "acquired"
    BUSY = "busy"
    BACKEND_ERROR = "backend_error"


@dataclass(frozen=True)
class SingleFlightAcquireResult:
    status: SingleFlightAcquireStatus
    lease: SingleFlightLease | None = field(default=None, repr=False)
    reason: str | None = None

    @property
    def acquired(self) -> bool:
        return self.status is SingleFlightAcquireStatus.ACQUIRED and self.lease is not None


@dataclass(frozen=True)
class SingleFlightReleaseResult:
    released: bool
    backend_error: bool = False
    reason: str | None = None


class LLMCacheStore(Protocol):
    backend_name: str

    def get(self, key: LLMCacheKey) -> CacheLookup: ...

    def put(
        self,
        key: LLMCacheKey,
        entry: CacheEntry,
        *,
        ttl_seconds: float,
    ) -> CacheWriteResult: ...

    def delete(self, key: LLMCacheKey) -> bool: ...


class SingleFlightCoordinator(Protocol):
    def acquire_singleflight(
        self,
        key: LLMCacheKey,
        *,
        owner_token: str,
        ttl_seconds: float,
    ) -> SingleFlightAcquireResult: ...

    def release_singleflight(
        self,
        lease: SingleFlightLease,
    ) -> SingleFlightReleaseResult: ...


def _non_empty_text(value: str) -> bool:
    return bool(value and value.strip())


def _text_or_empty(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dependency_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True
