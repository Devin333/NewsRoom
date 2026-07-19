from __future__ import annotations

from urllib.parse import urlsplit
from urllib.request import Request

from business.foundation.models.source import (
    SourceDefinition,
    SourceFetchPolicy as BusinessSourceFetchPolicy,
)
from business.layers.signal.source_health import ProbeObservation
from infrastructure.external.sources.fetch_policy import (
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from interfaces.services.source_mapping import to_infrastructure_fetch_policy


def default_source_health_probe(source: SourceDefinition, policy: BusinessSourceFetchPolicy) -> ProbeObservation:
    _ensure_http_url(source.url)
    infra_policy = to_infrastructure_fetch_policy(policy)

    def fetch() -> ProbeObservation:
        ensure_robots_allowed(source.url, infra_policy)
        request = Request(
            source.url,
            headers={
                "Accept": "*/*",
                "User-Agent": infra_policy.user_agent,
            },
        )
        with open_request_with_fetch_policy(request, infra_policy) as response:
            body = response.read(infra_policy.max_bytes + 1)
            status_code = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type")
            final_url = response.geturl()
        if len(body) > infra_policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {infra_policy.max_bytes}")
        return ProbeObservation(
            status_code=int(status_code) if status_code is not None else None,
            content_type=content_type,
            content_bytes=len(body),
            final_url=final_url,
        )

    return run_with_fetch_retries(fetch, infra_policy)


def _ensure_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must use http or https")


__all__ = ["default_source_health_probe"]
