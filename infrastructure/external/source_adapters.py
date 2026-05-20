from __future__ import annotations

from typing import Any

from infrastructure.external.sources import (
    ARXIV_API_URL,
    GITHUB_API_URL,
    ArxivConnector,
    DomainRateLimiter,
    FeedConnector,
    GithubConnector,
    HtmlConnector,
    ManualConnector,
    SourceFetchPolicy,
    effective_fetch_policy,
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from infrastructure.external.sources.fetch_policy import rate_limited_source_error
from infrastructure.external.sources.models import RawSourceItem, SourceError, SourceType


def default_arxiv_connector(**kwargs: Any) -> ArxivConnector:
    return ArxivConnector(**kwargs)


def default_github_connector(**kwargs: Any) -> GithubConnector:
    return GithubConnector(**kwargs)


__all__ = [
    "ARXIV_API_URL",
    "GITHUB_API_URL",
    "ArxivConnector",
    "DomainRateLimiter",
    "FeedConnector",
    "GithubConnector",
    "HtmlConnector",
    "ManualConnector",
    "RawSourceItem",
    "SourceError",
    "SourceFetchPolicy",
    "SourceType",
    "default_arxiv_connector",
    "default_github_connector",
    "effective_fetch_policy",
    "ensure_robots_allowed",
    "open_request_with_fetch_policy",
    "rate_limited_source_error",
    "run_with_fetch_retries",
]
