from __future__ import annotations

from dataclasses import replace
from typing import Any

from business.foundation.models.source import (
    Lineage,
    RawSourceItem,
    SourceDefinition,
    SourceError,
    SourceReliability,
    SourceType,
)
from infrastructure.external.sources.models import (
    RawSourceItem as InfraRawSourceItem,
    SourceDefinition as InfraSourceDefinition,
    SourceError as InfraSourceError,
    SourceReliability as InfraSourceReliability,
    SourceType as InfraSourceType,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_ports import (
    DailyFeedSourceConnector,
    DailyHtmlSourceConnector,
)


def fetch_official_blog(
    *,
    feed_connector: DailyFeedSourceConnector,
    html_connector: DailyHtmlSourceConnector,
    source: SourceDefinition,
    limit: int,
) -> tuple[list[Any], list[SourceError]]:
    infra_source = _infra_source(source)
    feed_items, feed_errors = feed_connector.fetch(infra_source, limit=limit)
    if feed_items:
        return _with_official_blog_fetch_metadata(
            [_business_raw_item(item) for item in feed_items],
            mode="feed",
        ), []

    html_items, html_errors = html_connector.fetch(infra_source, limit=limit)
    if html_items:
        return (
            _with_official_blog_fetch_metadata(
                [_business_raw_item(item) for item in html_items],
                mode="html_fallback",
                fallback_error_types=[error.error_type for error in feed_errors],
            ),
            [],
        )
    return [], [
        *_with_fallback_stage([_business_source_error(error) for error in feed_errors], "feed"),
        *_with_fallback_stage([_business_source_error(error) for error in html_errors], "html"),
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


def _infra_source(source: SourceDefinition) -> InfraSourceDefinition:
    return InfraSourceDefinition(
        source_id=source.source_id,
        name=source.name,
        source_type=InfraSourceType(SourceType(source.source_type).value),
        url=source.url,
        reliability=InfraSourceReliability(SourceReliability(source.reliability).value),
        authority_score=source.authority_score,
        enabled=source.enabled,
        fetch_interval_seconds=source.fetch_interval_seconds,
        respect_robots=source.respect_robots,
        user_agent=source.user_agent,
        topics=list(source.topics),
        category=source.category,
        language=source.language,
        region=source.region,
        metadata=dict(source.metadata),
    )


def _business_raw_item(item: InfraRawSourceItem) -> RawSourceItem:
    payload = item.to_dict()
    lineage_payload = payload.pop("lineage", None)
    return RawSourceItem(
        **payload,
        lineage=Lineage.from_dict(lineage_payload) if isinstance(lineage_payload, dict) else None,
    )


def _business_source_error(error: InfraSourceError) -> SourceError:
    return SourceError(
        source_id=error.source_id,
        source_name=error.source_name,
        error_type=error.error_type,
        error_message=error.error_message,
        url=error.url,
        retryable=error.retryable,
        request_ref=error.request_ref,
        response_ref=error.response_ref,
        occurred_at=error.occurred_at,
        metadata=dict(error.metadata),
    )
