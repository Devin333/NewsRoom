from __future__ import annotations

from domain.sources import SourceDefinition, SourceType


def source_connector_name(source: SourceDefinition) -> str:
    if source.source_type in {SourceType.RSS, SourceType.ATOM}:
        return "FeedConnector"
    if source.source_type == SourceType.OFFICIAL_BLOG:
        return "OfficialBlogFeedHtmlFallback"
    if source.source_type in {SourceType.HTML, SourceType.WEB_PAGE}:
        return "HtmlConnector"
    if source.source_type == SourceType.MANUAL:
        return "ManualConnector"
    if source.source_type == SourceType.ARXIV:
        return "ArxivConnector"
    if source.source_type == SourceType.GITHUB:
        return "GithubConnector"
    if source.source_type == SourceType.HACKERNEWS:
        return "HackerNewsConnector"
    if source.source_type == SourceType.REDDIT:
        return "RedditConnector"
    if source.source_type == SourceType.LOBSTERS:
        return "LobstersConnector"
    if source.source_type == SourceType.STACKOVERFLOW:
        return "StackOverflowConnector"
    if source.source_type == SourceType.DEVTO:
        return "DevToConnector"
    if source.source_type == SourceType.MEDIUM:
        return "MediumConnector"
    return "UnsupportedSourceConnector"
