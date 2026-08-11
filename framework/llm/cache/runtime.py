from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, replace
from typing import Callable

from framework.llm.cache.contracts import (
    CacheEligibility,
    CacheLookup,
    CacheLookupStatus,
    CacheMode,
    CacheWriteResult,
    CacheWriteStatus,
    LLMCacheStore,
    SingleFlightAcquireResult,
    SingleFlightAcquireStatus,
    SingleFlightCoordinator,
    SingleFlightLease,
)
from framework.llm.cache.entry import (
    CacheEntry,
    CacheResponseValidationError,
    CacheResponseValidator,
)
from framework.llm.cache.key import (
    CacheCanonicalizationError,
    LLMCacheKey,
    LLMCacheKeyFactory,
)
from framework.llm.cache.policy import LLMCachePolicy
from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse


@dataclass(frozen=True)
class CachePreparation:
    eligibility: CacheEligibility
    key: LLMCacheKey | None = None

    @property
    def eligible(self) -> bool:
        return self.eligibility.eligible and self.key is not None


@dataclass(frozen=True)
class CacheReadResult:
    lookup: CacheLookup
    response: LLMResponse | None = None

    @property
    def hit(self) -> bool:
        return self.lookup.hit and self.response is not None


@dataclass(frozen=True)
class SingleFlightAdmission:
    result: SingleFlightAcquireResult
    write_authorized: bool

    @property
    def lease(self) -> SingleFlightLease | None:
        return self.result.lease


class LLMCacheRuntime:
    def __init__(
        self,
        *,
        policy: LLMCachePolicy,
        key_factory: LLMCacheKeyFactory,
        store: LLMCacheStore,
        coordinator: SingleFlightCoordinator | None = None,
        singleflight_enabled: bool = True,
        singleflight_lock_ttl_seconds: float = 120.0,
        singleflight_wait_timeout_ms: int = 2_500,
        singleflight_poll_interval_ms: int = 50,
        replay_chunk_size: int = 1_024,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        owner_token_factory: Callable[[], str] | None = None,
    ) -> None:
        if singleflight_lock_ttl_seconds <= 0:
            raise ValueError("singleflight_lock_ttl_seconds must be greater than zero")
        if singleflight_wait_timeout_ms < 0:
            raise ValueError("singleflight_wait_timeout_ms must be non-negative")
        if singleflight_poll_interval_ms <= 0:
            raise ValueError("singleflight_poll_interval_ms must be greater than zero")
        if singleflight_wait_timeout_ms and (
            singleflight_poll_interval_ms > singleflight_wait_timeout_ms
        ):
            raise ValueError("singleflight poll interval cannot exceed wait timeout")
        if replay_chunk_size <= 0 or replay_chunk_size > 65_536:
            raise ValueError("replay_chunk_size must be between 1 and 65536")
        self.policy = policy
        self.key_factory = key_factory
        self.store = store
        self.coordinator = coordinator
        self.singleflight_enabled = bool(singleflight_enabled)
        self.singleflight_lock_ttl_seconds = float(singleflight_lock_ttl_seconds)
        self.singleflight_wait_timeout_seconds = singleflight_wait_timeout_ms / 1_000
        self.singleflight_poll_interval_seconds = singleflight_poll_interval_ms / 1_000
        self.replay_chunk_size = int(replay_chunk_size)
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._owner_token_factory = owner_token_factory or (lambda: secrets.token_urlsafe(24))

    @property
    def mode(self) -> CacheMode:
        return self.policy.mode

    @property
    def backend_name(self) -> str:
        return str(getattr(self.store, "backend_name", "unknown"))

    def prepare(
        self,
        *,
        request: LLMRequest,
        deployment_id: str,
        provider: str,
        model: str,
    ) -> CachePreparation:
        eligibility = self.policy.evaluate(request)
        if not eligibility.eligible or eligibility.context is None:
            return CachePreparation(eligibility=eligibility)
        try:
            key = self.key_factory.build(
                request=request,
                context=eligibility.context,
                deployment_id=deployment_id,
                provider=provider,
                model=model,
            )
        except (CacheCanonicalizationError, TypeError, ValueError):
            return CachePreparation(
                eligibility=replace(
                    eligibility,
                    eligible=False,
                    reason="unsupported_metadata",
                )
            )
        return CachePreparation(eligibility=eligibility, key=key)

    def read(self, preparation: CachePreparation, *, request: LLMRequest) -> CacheReadResult:
        if not preparation.eligible or preparation.key is None or not self.mode.reads:
            return CacheReadResult(
                lookup=CacheLookup(
                    status=CacheLookupStatus.MISS,
                    reason="read_not_enabled",
                    backend=self.backend_name,
                )
            )
        try:
            lookup = self.store.get(preparation.key)
        except Exception as exc:
            return CacheReadResult(
                lookup=CacheLookup(
                    status=CacheLookupStatus.BACKEND_ERROR,
                    reason=type(exc).__name__,
                    backend=self.backend_name,
                )
            )
        if not lookup.hit or lookup.entry is None:
            return CacheReadResult(lookup=lookup)
        try:
            lookup.entry.validate_identity(preparation.key)
            response = lookup.entry.to_response(request=request)
        except (CacheResponseValidationError, TypeError, ValueError):
            self._delete_best_effort(preparation.key)
            return CacheReadResult(
                lookup=CacheLookup(
                    status=CacheLookupStatus.CORRUPT,
                    reason="entry_validation_failed",
                    backend=lookup.backend,
                )
            )
        return CacheReadResult(lookup=lookup, response=response)

    def write(
        self,
        preparation: CachePreparation,
        *,
        request: LLMRequest,
        response: LLMResponse,
        write_authorized: bool = True,
    ) -> CacheWriteResult:
        if not preparation.eligible or preparation.key is None or not self.mode.writes:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason="write_not_enabled",
                backend=self.backend_name,
            )
        if not write_authorized:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason="singleflight_not_owner",
                backend=self.backend_name,
            )
        try:
            entry = CacheEntry.from_response(
                key=preparation.key,
                request=request,
                response=response,
            )
            size_bytes = len(entry.to_json_bytes())
        except (CacheResponseValidationError, TypeError, ValueError) as exc:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason=_validation_reason(exc),
                backend=self.backend_name,
            )
        if size_bytes > self.policy.max_entry_bytes:
            return CacheWriteResult(
                status=CacheWriteStatus.ENTRY_TOO_LARGE,
                reason="entry_too_large",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        ttl = self.policy.ttl_seconds
        if ttl is None:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason="missing_finite_ttl",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        try:
            return self.store.put(
                preparation.key,
                entry,
                ttl_seconds=float(ttl),
            )
        except Exception as exc:
            return CacheWriteResult(
                status=CacheWriteStatus.BACKEND_ERROR,
                reason=type(exc).__name__,
                size_bytes=size_bytes,
                backend=self.backend_name,
            )

    def admit_singleflight(self, preparation: CachePreparation) -> SingleFlightAdmission:
        if (
            not preparation.eligible
            or preparation.key is None
            or not self.mode.reads
            or not self.singleflight_enabled
            or self.coordinator is None
        ):
            return SingleFlightAdmission(
                result=SingleFlightAcquireResult(
                    status=SingleFlightAcquireStatus.ACQUIRED,
                ),
                write_authorized=True,
            )
        try:
            result = self.coordinator.acquire_singleflight(
                preparation.key,
                owner_token=self._owner_token_factory(),
                ttl_seconds=self.singleflight_lock_ttl_seconds,
            )
        except Exception as exc:
            result = SingleFlightAcquireResult(
                status=SingleFlightAcquireStatus.BACKEND_ERROR,
                reason=type(exc).__name__,
            )
        return SingleFlightAdmission(result=result, write_authorized=result.acquired)

    def wait_for_entry(
        self,
        preparation: CachePreparation,
        *,
        request: LLMRequest,
    ) -> CacheReadResult:
        if not preparation.eligible or preparation.key is None or not self.mode.reads:
            return CacheReadResult(
                lookup=CacheLookup(
                    status=CacheLookupStatus.MISS,
                    reason="wait_not_enabled",
                    backend=self.backend_name,
                )
            )
        context = preparation.eligibility.context
        deadline = self._clock() + self.singleflight_wait_timeout_seconds
        if context is not None and context.deadline_monotonic is not None:
            deadline = min(deadline, context.deadline_monotonic)
        last = CacheReadResult(
            lookup=CacheLookup(status=CacheLookupStatus.MISS, backend=self.backend_name)
        )
        while self._clock() < deadline:
            remaining = deadline - self._clock()
            self._sleep(min(self.singleflight_poll_interval_seconds, max(0.0, remaining)))
            last = self.read(preparation, request=request)
            if last.hit or last.lookup.status in {
                CacheLookupStatus.CORRUPT,
                CacheLookupStatus.BACKEND_ERROR,
            }:
                return last
        return replace(
            last,
            lookup=replace(last.lookup, reason=last.lookup.reason or "singleflight_wait_timeout"),
        )

    def release_singleflight(self, lease: SingleFlightLease | None) -> None:
        if lease is None or self.coordinator is None:
            return
        try:
            self.coordinator.release_singleflight(lease)
        except Exception:
            return

    def validate_response(self, *, request: LLMRequest, response: LLMResponse) -> None:
        CacheResponseValidator.validate(request=request, response=response)

    def _delete_best_effort(self, key: LLMCacheKey) -> None:
        try:
            self.store.delete(key)
        except Exception:
            return


def _validation_reason(error: BaseException) -> str:
    message = str(error)
    if "tool call" in message:
        return "tool_call_present"
    if "structured output" in message or "JSON response" in message:
        return "output_contract_validation_failed"
    return "response_not_cacheable"
