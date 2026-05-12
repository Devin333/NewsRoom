"""Source connector implementations."""

from sources.connectors.arxiv import ARXIV_API_URL, ArxivConnector, ArxivQuery
from sources.connectors.feed import FeedConnector, SourceFetchPolicy
from sources.connectors.github import (
    GITHUB_API_URL,
    GithubConnector,
    GithubRepository,
    GithubRepositorySearchResult,
)

__all__ = [
    "ARXIV_API_URL",
    "ArxivConnector",
    "ArxivQuery",
    "FeedConnector",
    "GITHUB_API_URL",
    "GithubConnector",
    "GithubRepository",
    "GithubRepositorySearchResult",
    "SourceFetchPolicy",
]
