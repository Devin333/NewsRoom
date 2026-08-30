from __future__ import annotations

from urllib.error import HTTPError

import pytest

from backend.foundation.models.source import SourceDefinition, SourceFetchPolicy
from backend.foundation.registry.source_registry import SourceRegistry
from backend.layers.signal.source_health import (
    BasicSourceHealthManager,
    SourceHealthChecker,
)
from infrastructure.external.sources import DomainRateLimiter, RobotsDisallowedError
from infrastructure.external.sources.fetch_policy import fetch_attempts
from interfaces.services.source_health_probe import default_source_health_probe
from interfaces.services.source_runtime import SourceRateLimiterAdapter


def test_default_source_health_probe_retries_robots_transport_failure(monkeypatch) -> None:
    robots_calls = 0
    fetch_calls = 0

    class Headers:
        def get(self, name, default=None):
            return "text/html" if name == "Content-Type" else default

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return b"ok"

        def getcode(self):
            return self.status

        def geturl(self):
            return "https://example.com/health"

    def ensure_robots(_url, _policy):
        nonlocal robots_calls
        robots_calls += 1
        if robots_calls == 1:
            raise HTTPError(
                "https://example.com/robots.txt",
                503,
                "temporarily unavailable",
                hdrs=None,
                fp=None,
            )

    def open_request(_request, _policy):
        nonlocal fetch_calls
        fetch_calls += 1
        return Response()

    monkeypatch.setattr(
        "interfaces.services.source_health_probe.ensure_robots_allowed",
        ensure_robots,
    )
    monkeypatch.setattr(
        "interfaces.services.source_health_probe.open_request_with_fetch_policy",
        open_request,
    )

    observation = default_source_health_probe(
        _source(),
        SourceFetchPolicy(
            respect_robots=True,
            retry_times=1,
            retry_on_status_codes=(503,),
        ),
    )

    assert observation.status_code == 200
    assert observation.content_bytes == 2
    assert robots_calls == 2
    assert fetch_calls == 1


def test_health_checker_reserves_once_across_probe_retries(monkeypatch) -> None:
    robots_calls = 0
    fetch_calls = 0

    class Headers:
        def get(self, name, default=None):
            return "text/html" if name == "Content-Type" else default

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return b"ok"

        def getcode(self):
            return self.status

        def geturl(self):
            return "https://example.com/health"

    class CountingLimiter:
        def __init__(self) -> None:
            self.delegate = SourceRateLimiterAdapter(DomainRateLimiter())
            self.calls = 0

        def reserve(self, url: str, *, limit_per_minute: int | None):
            self.calls += 1
            return self.delegate.reserve(
                url,
                limit_per_minute=limit_per_minute,
            )

    def ensure_robots(_url, _policy):
        nonlocal robots_calls
        robots_calls += 1
        if robots_calls == 1:
            raise HTTPError(
                "https://example.com/robots.txt",
                503,
                "temporarily unavailable",
                hdrs=None,
                fp=None,
            )

    def open_request(_request, _policy):
        nonlocal fetch_calls
        fetch_calls += 1
        return Response()

    monkeypatch.setattr(
        "interfaces.services.source_health_probe.ensure_robots_allowed",
        ensure_robots,
    )
    monkeypatch.setattr(
        "interfaces.services.source_health_probe.open_request_with_fetch_policy",
        open_request,
    )
    limiter = CountingLimiter()
    result = SourceHealthChecker(
        SourceRegistry([_source()]),
        BasicSourceHealthManager(),
        fetch_policy=SourceFetchPolicy(
            respect_robots=True,
            retry_times=1,
            retry_on_status_codes=(503,),
            rate_limit_per_domain_per_minute=1,
        ),
        probe_fetcher=default_source_health_probe,
        rate_limiter=limiter,
    ).run()

    assert result.succeeded_count == 1
    assert limiter.calls == 1
    assert robots_calls == 2
    assert fetch_calls == 1


def test_default_source_health_probe_does_not_retry_robots_denial(monkeypatch) -> None:
    robots_calls = 0
    fetch_calls = 0

    def deny_robots(url, policy):
        nonlocal robots_calls
        robots_calls += 1
        raise RobotsDisallowedError(
            url,
            "https://example.com/robots.txt",
            policy.user_agent,
        )

    def open_request(_request, _policy):
        nonlocal fetch_calls
        fetch_calls += 1
        raise AssertionError("content probe must not run after robots denial")

    monkeypatch.setattr(
        "interfaces.services.source_health_probe.ensure_robots_allowed",
        deny_robots,
    )
    monkeypatch.setattr(
        "interfaces.services.source_health_probe.open_request_with_fetch_policy",
        open_request,
    )

    with pytest.raises(RobotsDisallowedError) as captured:
        default_source_health_probe(
            _source(),
            SourceFetchPolicy(respect_robots=True, retry_times=3),
        )

    assert fetch_attempts(captured.value) == 1
    assert robots_calls == 1
    assert fetch_calls == 0


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="health-source",
        name="Health Source",
        source_type="html",
        url="https://example.com/health",
    )
