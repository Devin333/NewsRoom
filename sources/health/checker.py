from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceHealth,
    SourceHealthStatus,
    SourcePipelineEvent,
)
from sources import SourceRegistry
from sources.connectors.fetch_policy import (
    RobotsDisallowedError,
    SourceFetchPolicy,
    TooManyRedirectsError,
    UnsupportedContentTypeError,
    effective_fetch_policy,
    ensure_robots_allowed,
    fetch_attempts,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from sources.health.manager import BasicSourceHealthManager


ProbeFetcher = Callable[[SourceDefinition, SourceFetchPolicy], "ProbeObservation"]


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
    ) -> None:
        self.source_registry = source_registry
        self.health_manager = health_manager
        self.fetch_policy = fetch_policy or SourceFetchPolicy(max_bytes=128_000)
        self.probe_fetcher = probe_fetcher or _default_probe_fetcher

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

        events.append(_event("source_probe_started", source, force=force))
        latency_start = perf_counter()
        try:
            policy = effective_fetch_policy(self.fetch_policy, source)
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
            if health.status == SourceHealthStatus.COOLING_DOWN:
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


def _default_probe_fetcher(source: SourceDefinition, policy: SourceFetchPolicy) -> ProbeObservation:
    _ensure_http_url(source.url)
    ensure_robots_allowed(source.url, policy)

    def fetch() -> ProbeObservation:
        request = Request(
            source.url,
            headers={
                "Accept": "*/*",
                "User-Agent": policy.user_agent,
            },
        )
        with open_request_with_fetch_policy(request, policy) as response:
            body = response.read(policy.max_bytes + 1)
            status_code = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type")
            final_url = response.geturl()
        if len(body) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return ProbeObservation(
            status_code=int(status_code) if status_code is not None else None,
            content_type=content_type,
            content_bytes=len(body),
            final_url=final_url,
        )

    return run_with_fetch_retries(fetch, policy)


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
            "source_type": source.source_type.value,
            "url": source.url,
            **{key: value for key, value in metadata.items() if value is not None},
        },
    )


def _exception_source_error(source: SourceDefinition, exc: Exception) -> SourceError:
    error_type, retryable, health_affecting = _classify_probe_exception(exc)
    metadata: dict[str, Any] = {
        "phase": "probe",
        "retryable": retryable,
        "source_health_affecting": health_affecting,
        "original_exception_type": type(exc).__name__,
    }
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    if isinstance(exc, UnsupportedContentTypeError):
        metadata["content_type"] = exc.content_type
        metadata["supported_content_types"] = list(exc.supported_content_types)
    if isinstance(exc, TooManyRedirectsError):
        metadata["redirect_url"] = exc.url
        metadata["max_redirects"] = exc.max_redirects
    if isinstance(exc, RobotsDisallowedError):
        metadata["robots_url"] = exc.robots_url
        metadata["user_agent"] = exc.user_agent
    attempts = fetch_attempts(exc)
    if attempts is not None:
        metadata["attempts"] = attempts
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=error_type,
        error_message=str(exc),
        url=source.url,
        retryable=retryable,
        metadata=metadata,
    )


def _classify_probe_exception(exc: Exception) -> tuple[str, bool, bool]:
    if isinstance(exc, RobotsDisallowedError):
        return "robots_disallowed", False, False
    if isinstance(exc, TooManyRedirectsError):
        return "too_many_redirects", False, False
    if isinstance(exc, UnsupportedContentTypeError):
        return "unsupported_content_type", False, False
    if isinstance(exc, HTTPError):
        if 400 <= exc.code < 500:
            return "fetch_http_4xx", exc.code in {408, 409, 425, 429}, True
        if exc.code >= 500:
            return "fetch_http_5xx", True, True
        return "fetch_connection_error", True, True
    if _is_timeout_exception(exc):
        return "fetch_timeout", True, True
    if isinstance(exc, ValueError) and "max_bytes" in str(exc):
        return "max_bytes_exceeded", False, False
    if isinstance(exc, ValueError):
        return "invalid_source_config", False, False
    return "fetch_connection_error", True, True


def _ensure_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must use http or https")


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
