from __future__ import annotations

from dataclasses import replace
from typing import Any

from domain.sources import SourceDefinition, SourceError
from sources.connectors import FeedConnector, HtmlConnector


def fetch_official_blog(
    *,
    feed_connector: FeedConnector,
    html_connector: HtmlConnector,
    source: SourceDefinition,
    limit: int,
) -> tuple[list[Any], list[SourceError]]:
    feed_items, feed_errors = feed_connector.fetch(source, limit=limit)
    if feed_items:
        return _with_official_blog_fetch_metadata(feed_items, mode="feed"), []

    html_items, html_errors = html_connector.fetch(source, limit=limit)
    if html_items:
        return (
            _with_official_blog_fetch_metadata(
                html_items,
                mode="html_fallback",
                fallback_error_types=[error.error_type for error in feed_errors],
            ),
            [],
        )
    return [], [
        *_with_fallback_stage(feed_errors, "feed"),
        *_with_fallback_stage(html_errors, "html"),
    ]


def _with_official_blog_fetch_metadata(
    items: list[Any],
    *,
    mode: str,
    fallback_error_types: list[str] | None = None,
) -> list[Any]:
    annotated = []
    for item in items:
        metadata = dict(getattr(item, "metadata", {}) or {})
        metadata["official_blog_fetch_mode"] = mode
        if fallback_error_types:
            metadata["official_blog_fallback"] = {
                "from": "feed",
                "to": "html",
                "feed_error_types": list(fallback_error_types),
            }
        annotated.append(replace(item, metadata=metadata))
    return annotated


def _with_fallback_stage(errors: list[SourceError], stage: str) -> list[SourceError]:
    staged = []
    for error in errors:
        metadata = dict(error.metadata)
        metadata["official_blog_fallback_stage"] = stage
        staged.append(replace(error, metadata=metadata))
    return staged
