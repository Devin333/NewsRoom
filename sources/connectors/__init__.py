"""Source connector implementations."""

from sources.connectors.arxiv import ARXIV_API_URL, ArxivConnector, ArxivQuery
from sources.connectors.community import (
    DEVTO_API_URL,
    LOBSTERS_BASE_URL,
    MEDIUM_BASE_URL,
    STACKOVERFLOW_API_URL,
    DevToConnector,
    LobstersConnector,
    MediumConnector,
    StackOverflowConnector,
    build_devto_articles_url,
    build_lobsters_url,
    build_medium_feed_url,
    build_stackoverflow_questions_url,
)
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
    "DEVTO_API_URL",
    "DevToConnector",
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
    "LOBSTERS_BASE_URL",
    "LobstersConnector",
    "MEDIUM_BASE_URL",
    "MediumConnector",
    "ManualConnector",
    "RateLimitDecision",
    "REDDIT_BASE_URL",
    "RedditConnector",
    "RobotsDisallowedError",
    "STACKOVERFLOW_API_URL",
    "SourceFetchPolicy",
    "StackOverflowConnector",
    "TooManyRedirectsError",
    "build_devto_articles_url",
    "build_hackernews_item_url",
    "build_hackernews_story_list_url",
    "build_lobsters_url",
    "build_medium_feed_url",
    "build_reddit_listing_url",
    "build_stackoverflow_questions_url",
    "effective_fetch_policy",
    "ensure_robots_allowed",
    "extract_html",
    "open_request_with_fetch_policy",
    "run_with_fetch_retries",
]
