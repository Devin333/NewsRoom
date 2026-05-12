"""Source connector implementations."""

from sources.connectors.arxiv import ARXIV_API_URL, ArxivConnector, ArxivQuery
from sources.connectors.feed import FeedConnector
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    RateLimitDecision,
    RobotsDisallowedError,
    SourceFetchPolicy,
    TooManyRedirectsError,
    effective_fetch_policy,
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from sources.connectors.github import (
    GITHUB_API_URL,
    GithubConnector,
    GithubRepository,
    GithubRepositorySearchResult,
)
from sources.connectors.html import HtmlConnector, HtmlExtractionResult, extract_html
from sources.connectors.manual import ManualConnector

__all__ = [
    "ARXIV_API_URL",
    "ArxivConnector",
    "ArxivQuery",
    "DomainRateLimiter",
    "FeedConnector",
    "GITHUB_API_URL",
    "GithubConnector",
    "GithubRepository",
    "GithubRepositorySearchResult",
    "HtmlConnector",
    "HtmlExtractionResult",
    "ManualConnector",
    "RateLimitDecision",
    "RobotsDisallowedError",
    "SourceFetchPolicy",
    "TooManyRedirectsError",
    "effective_fetch_policy",
    "ensure_robots_allowed",
    "extract_html",
    "open_request_with_fetch_policy",
    "run_with_fetch_retries",
]
