"""Source connector implementations."""

from sources.connectors.arxiv import ARXIV_API_URL, ArxivConnector, ArxivQuery
from sources.connectors.feed import FeedConnector
from sources.connectors.fetch_policy import (
    DomainRateLimiter,
    RateLimitDecision,
    SourceFetchPolicy,
    run_with_fetch_retries,
)
from sources.connectors.github import (
    GITHUB_API_URL,
    GithubConnector,
    GithubRepository,
    GithubRepositorySearchResult,
)
from sources.connectors.html import HtmlConnector, HtmlExtractionResult, extract_html

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
    "RateLimitDecision",
    "SourceFetchPolicy",
    "extract_html",
    "run_with_fetch_retries",
]
