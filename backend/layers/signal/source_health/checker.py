from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
from time import perf_counter
from typing import Any
from urllib.error import HTTPError

from backend.foundation.models.source import (
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
    SourceHealth,
    SourceHealthStatus,
    SourcePipelineEvent,
    SourceType,
)
from backend.foundation.registry.source_registry import SourceRegistry
from backend.layers.signal.source_health.manager import BasicSourceHealthManager
from backend.layers.signal.source_processing.error_metadata import (
    SourceErrorMetadataInput,
    source_error_metadata,
)
from backend.layers.signal.source_processing.error_taxonomy import (
    SourceTaxonomyExtension,
    classify_source_exception,
    effective_source_retryable,
)
from backend.layers.signal.source_tool_runtime import (
    SourceRateLimiter,
    effective_source_fetch_policy,
    source_rate_limited_error,
)


ProbeFetcher = Callable[[SourceDefinition, SourceFetchPolicy], "ProbeObservation"]
UTC = _tz.utc


@dataclass(frozen=True)
class ProbeObservation:
    status_code: int | None
    content_type: str | None
    content_bytes: int
    final_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "content_type": self.content_type,
            "content_bytes": self.content_bytes,
            "final_url": self.final_url,
        }


@dataclass(frozen=True)
class SourceHealthCheckEntry:
    source_id: str
    source_name: str
    url: str
    status: str
    ok: bool
    skipped: bool = False
    skip_reason: str | None = None
    latency_ms: float | None = None
    observation: ProbeObservation | None = None
    health: SourceHealth | None = None
    error: SourceError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "url": self.url,
            "status": self.status,
            "ok": self.ok,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "latency_ms": self.latency_ms,
            "observation": self.observation.to_dict() if self.observation else None,
            "health": self.health.to_dict() if self.health else None,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass(frozen=True)
class SourceHealthCheckResult:
    checked_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    entries: list[SourceHealthCheckEntry] = field(default_factory=list)
    events: list[SourcePipelineEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_count": self.checked_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "entries": [entry.to_dict() for entry in self.entries],
            "events": [event.to_dict() for event in self.events],
        }


class SourceHealthChecker:
    def __init__(
        self,
        source_registry: SourceRegistry,
        health_manager: BasicSourceHealthManager,
        *,
        fetch_policy: SourceFetchPolicy | None = None,
        probe_fetcher: ProbeFetcher | None = None,
        rate_limiter: SourceRateLimiter | None = None,
    ) -> None:
        self.source_registry = source_registry
        self.health_manager = health_manager
        if fetch_policy is not None and not isinstance(fetch_policy, SourceFetchPolicy):
            raise TypeError("SourceHealthChecker.fetch_policy must be a business SourceFetchPolicy")
        self.fetch_policy = fetch_policy or SourceFetchPolicy(max_bytes=128_000)
        self.probe_fetcher = probe_fetcher or _missing_probe_fetcher
        self.rate_limiter = rate_limiter

    def run(
        self,
        *,
        source_id: str | None = None,
        enabled_only: bool = True,
        limit: int | None = None,
        force: bool = False,
    ) -> SourceHealthCheckResult:
        sources = self._selected_sources(source_id=source_id, enabled_only=enabled_only, limit=limit)
        entries: list[SourceHealthCheckEntry] = []
        events: list[SourcePipelineEvent] = []
        for source in sources:
            entry, source_events = self._check_source(source, force=force)
            entries.append(entry)
            events.extend(source_events)
        return SourceHealthCheckResult(
            checked_count=len(entries),
            succeeded_count=sum(1 for entry in entries if entry.ok and not entry.skipped),
            failed_count=sum(1 for entry in entries if not entry.ok and not entry.skipped),
            skipped_count=sum(1 for entry in entries if entry.skipped),
            entries=entries,
            events=events,
        )

    def _selected_sources(
        self,
        *,
        source_id: str | None,
        enabled_only: bool,
        limit: int | None,
    ) -> list[SourceDefinition]:
        if source_id:
            source = self.source_registry.get(source_id)
            if enabled_only and not source.enabled:
                return []
            return [source]
        sources = self.source_registry.list_sources(enabled_only=enabled_only)
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            sources = sources[:limit]
        return sources

    def _check_source(
        self,
        source: SourceDefinition,
        *,
        force: bool,
    ) -> tuple[SourceHealthCheckEntry, list[SourcePipelineEvent]]:
        events: list[SourcePipelineEvent] = []
        if not source.enabled:
            health = self.health_manager.record_disabled(
                source.source_id,
                reason="source disabled by configuration",
                source_name=source.name,
                url=source.url,
            )
            return (
                _entry(source, status=health.status.value, ok=False, skipped=True, skip_reason="disabled", health=health),
                [_event("source_health_updated", source, status=health.status.value)],
            )

        if self.health_manager.should_skip(source.source_id) and not force:
            health = self.health_manager.get(source.source_id, source_name=source.name, url=source.url)
            return (
                _entry(source, status=health.status.value, ok=False, skipped=True, skip_reason="cooldown", health=health),
                [
                    _event(
                        "source_fetch_skipped",
                        source,
                        reason="cooldown",
                        cooldown_until=_dt(health.cooldown_until),
                    )
                ],
            )

        policy = effective_source_fetch_policy(self.fetch_policy, source)
        rate_limit_error = _rate_limit_error(source, policy, self.rate_limiter)
        if rate_limit_error is not None:
            health = self.health_manager.get(
                source.source_id,
                source_name=source.name,
                url=source.url,
            )
            return (
                _entry(
                    source,
                    status=health.status.value,
                    ok=False,
                    skipped=True,
                    skip_reason="rate_limited",
                    health=health,
                    error=rate_limit_error,
                ),
                [
                    _event(
                        "source_fetch_skipped",
                        source,
                        reason="rate_limited",
                        domain=rate_limit_error.metadata.get("domain"),
                        retry_after_seconds=rate_limit_error.metadata.get(
                            "retry_after_seconds"
                        ),
                    ),
                    _event(
                        "source_health_updated",
                        source,
                        status=health.status.value,
                        consecutive_failures=health.consecutive_failures,
                    ),
                ],
            )

        events.append(_event("source_probe_started", source, force=force))
        latency_start = perf_counter()
        try:
            observation = self.probe_fetcher(source, policy)
        except Exception as exc:
            latency_ms = _elapsed_ms(latency_start)
            error = _exception_source_error(source, exc)
            health = self.health_manager.record_failure(
                source.source_id,
                error,
                latency_ms=latency_ms,
                source_name=source.name,
                url=source.url,
            )
            events.append(
                _event(
                    "source_probe_failed",
                    source,
                    error_type=error.error_type,
                    latency_ms=latency_ms,
                )
            )
            if health.status == SourceHealthStatus.DOWN:
                events.append(
                    _event(
                        "source_cooldown_started",
                        source,
                        cooldown_until=_dt(health.cooldown_until),
                        consecutive_failures=health.consecutive_failures,
                    )
                )
            events.append(
                _event(
                    "source_health_updated",
                    source,
                    status=health.status.value,
                    consecutive_failures=health.consecutive_failures,
                )
            )
            return (
                _entry(
                    source,
                    status=health.status.value,
                    ok=False,
                    latency_ms=latency_ms,
                    health=health,
                    error=error,
                ),
                events,
            )

        latency_ms = _elapsed_ms(latency_start)
        health = self.health_manager.record_success(
            source.source_id,
            latency_ms=latency_ms,
            source_name=source.name,
            url=source.url,
        )
        events.append(
            _event(
                "source_probe_succeeded",
                source,
                latency_ms=latency_ms,
                status_code=observation.status_code,
                content_bytes=observation.content_bytes,
            )
        )
        events.append(
            _event(
                "source_health_updated",
                source,
                status=health.status.value,
                consecutive_failures=health.consecutive_failures,
            )
        )
        return (
            _entry(
                source,
                status=health.status.value,
                ok=True,
                latency_ms=latency_ms,
                observation=observation,
                health=health,
            ),
            events,
        )


def _missing_probe_fetcher(source: SourceDefinition, policy: SourceFetchPolicy) -> ProbeObservation:
    raise RuntimeError("source health probe_fetcher is required")


def _entry(
    source: SourceDefinition,
    *,
    status: str,
    ok: bool,
    skipped: bool = False,
    skip_reason: str | None = None,
    latency_ms: float | None = None,
    observation: ProbeObservation | None = None,
    health: SourceHealth | None = None,
    error: SourceError | None = None,
) -> SourceHealthCheckEntry:
    return SourceHealthCheckEntry(
        source_id=source.source_id,
        source_name=source.name,
        url=source.url,
        status=status,
        ok=ok,
        skipped=skipped,
        skip_reason=skip_reason,
        latency_ms=latency_ms,
        observation=observation,
        health=health,
        error=error,
    )


def _event(event_type: str, source: SourceDefinition, **metadata: Any) -> SourcePipelineEvent:
    return SourcePipelineEvent(
        event_type=event_type,
        source_id=source.source_id,
        metadata={
            "source_name": source.name,
            "source_type": _source_type(source).value,
            "url": source.url,
            **{key: value for key, value in metadata.items() if value is not None},
        },
    )


def _exception_source_error(source: SourceDefinition, exc: Exception) -> SourceError:
    classification = classify_source_exception(
        exc,
        phase="probe",
        extension=SourceTaxonomyExtension(invalid_config_keywords=("source url",)),
        effective_retryable=effective_source_retryable(exc),
    )
    extra: dict[str, Any] = {}
    if isinstance(exc, HTTPError):
        extra["status_code"] = exc.code
    exception_type = type(exc).__name__
    if exception_type == "UnsupportedContentTypeError":
        extra["content_type"] = getattr(exc, "content_type", None)
        extra["supported_content_types"] = list(getattr(exc, "supported_content_types", ()) or ())
    if exception_type == "TooManyRedirectsError":
        extra["redirect_url"] = getattr(exc, "url", None)
        extra["max_redirects"] = getattr(exc, "max_redirects", None)
    if exception_type == "RobotsDisallowedError":
        extra["robots_url"] = getattr(exc, "robots_url", None)
        extra["user_agent"] = getattr(exc, "user_agent", None)
    attempts = getattr(exc, "source_fetch_attempts", None)
    if attempts is not None:
        extra["attempts"] = attempts
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=classification.error_type,
        error_message=str(exc),
        url=source.url,
        retryable=classification.retryable,
        metadata=source_error_metadata(
            SourceErrorMetadataInput(
                phase="probe",
                retryable=classification.retryable,
                source_health_affecting=classification.source_health_affecting,
                workflow_blocking=classification.workflow_blocking,
                operator_action_required=classification.operator_action_required,
                original_exception_type=type(exc).__name__,
                extra=extra,
            )
        ),
    )


def _rate_limit_error(
    source: SourceDefinition,
    policy: SourceFetchPolicy,
    rate_limiter: SourceRateLimiter | None,
) -> SourceError | None:
    if policy.rate_limit_per_domain_per_minute is None:
        return None
    if rate_limiter is None:
        raise RuntimeError(
            "source rate limiter adapter is required when rate limiting is enabled"
        )
    decision = rate_limiter.reserve(
        source.url,
        limit_per_minute=policy.rate_limit_per_domain_per_minute,
    )
    if decision.allowed:
        return None
    return source_rate_limited_error(
        source,
        decision,
        url=source.url,
    )


def _source_type(source: SourceDefinition) -> SourceType:
    return SourceType(source.source_type)


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
