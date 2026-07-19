from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from business.foundation.models.source import (
    RawSourceItem,
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
)
from business.layers.signal.source_processing.error_metadata import (
    SourceErrorMetadataInput,
    source_error_metadata,
)


FetchText = Callable[[str], str]


@dataclass(frozen=True)
class SourceTextFetchResult:
    content: str
    status_code: int | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class SourceRateLimitDecision:
    allowed: bool
    domain: str
    limit_per_minute: int | None
    window_seconds: int = 60
    retry_after_seconds: int | None = None


class SourceRateLimiter(Protocol):
    def reserve(self, url: str, *, limit_per_minute: int | None) -> SourceRateLimitDecision:
        ...


class SourceToolRuntime(Protocol):
    def fetch_text(self, url: str, policy: SourceFetchPolicy) -> SourceTextFetchResult:
        ...

    def parse_feed(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        ...

    def parse_html(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        ...

    def fetch_manual(
        self,
        source: SourceDefinition,
        *,
        records: Sequence[dict[str, object]],
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        ...

    def fetch_official_blog(
        self,
        source: SourceDefinition,
        *,
        policy: SourceFetchPolicy,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        ...


def effective_source_fetch_policy(
    policy: SourceFetchPolicy,
    source: SourceDefinition,
) -> SourceFetchPolicy:
    return replace(
        policy,
        respect_robots=policy.respect_robots and source.respect_robots,
        user_agent=source.user_agent or policy.user_agent,
    )


def source_rate_limited_error(
    source: SourceDefinition,
    decision: SourceRateLimitDecision,
    *,
    url: str,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="rate_limited",
        error_message=f"source fetch rate limit reached for domain: {decision.domain}",
        url=url,
        retryable=True,
        metadata=source_error_metadata(
            SourceErrorMetadataInput(
                phase="fetch",
                retryable=True,
                source_health_affecting=False,
                workflow_blocking=False,
                extra={
                    "domain": decision.domain,
                    "limit_per_minute": decision.limit_per_minute,
                    "window_seconds": decision.window_seconds,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
        ),
    )


def source_fetch_policy_without_rate_limit(policy: SourceFetchPolicy) -> SourceFetchPolicy:
    return replace(policy, rate_limit_per_domain_per_minute=None)


__all__ = [
    "FetchText",
    "SourceRateLimitDecision",
    "SourceRateLimiter",
    "SourceTextFetchResult",
    "SourceToolRuntime",
    "effective_source_fetch_policy",
    "source_fetch_policy_without_rate_limit",
    "source_rate_limited_error",
]
