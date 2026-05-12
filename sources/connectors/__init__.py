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
from sources.connectors.hackernews import (
    HACKERNEWS_API_URL,
    HackerNewsConnector,
    build_hackernews_item_url,
    build_hackernews_story_list_url,
)
from sources.connectors.html import HtmlConnector, HtmlExtractionResult, extract_html
from sources.connectors.manual import ManualConnector
from sources.connectors.reddit import REDDIT_BASE_URL, RedditConnector, build_reddit_listing_url

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
    "HACKERNEWS_API_URL",
    "HackerNewsConnector",
    "HtmlConnector",
    "HtmlExtractionResult",
    "ManualConnector",
    "RateLimitDecision",
    "REDDIT_BASE_URL",
    "RedditConnector",
    "RobotsDisallowedError",
    "SourceFetchPolicy",
    "TooManyRedirectsError",
    "build_hackernews_item_url",
    "build_hackernews_story_list_url",
    "build_reddit_listing_url",
    "effective_fetch_policy",
    "ensure_robots_allowed",
    "extract_html",
    "open_request_with_fetch_policy",
    "run_with_fetch_retries",
]
