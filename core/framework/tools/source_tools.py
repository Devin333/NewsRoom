from __future__ import annotations

from datetime import datetime
from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.sources import RawSourceItem, SourceDefinition, SourceType
from sources.connectors import FeedConnector
from sources.processing.normalize import canonicalize_url


def register_source_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="source.parse_rss",
            description="Parse RSS XML into raw source items.",
            input_schema=_parse_feed_schema(),
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: _parse_feed(args, default_source_type=SourceType.RSS),
    )
    registry.register(
        ToolDefinition(
            name="source.parse_atom",
            description="Parse Atom XML into raw source items.",
            input_schema=_parse_feed_schema(),
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: _parse_feed(args, default_source_type=SourceType.ATOM),
    )
    registry.register(
        ToolDefinition(
            name="source.normalize_url",
            description="Canonicalize a source URL and strip known tracking parameters.",
            input_schema={
                "required": ["url"],
                "properties": {"url": {"type": "string"}},
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: {"canonical_url": canonicalize_url(str(args["url"]))},
    )


def _parse_feed_schema() -> dict[str, Any]:
    return {
        "required": ["source", "xml"],
        "properties": {
            "source": {"type": "object"},
            "xml": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _parse_feed(args: dict[str, Any], *, default_source_type: SourceType) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=default_source_type)
    limit = args.get("limit")
    items = FeedConnector().parse(
        source,
        str(args["xml"]),
        limit=int(limit) if limit is not None else None,
    )
    return {
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
    }


def _source_definition(payload: Any, *, default_source_type: SourceType) -> SourceDefinition:
    if not isinstance(payload, dict):
        raise ValueError("source must be an object")
    return SourceDefinition(
        source_id=str(payload.get("source_id") or ""),
        name=str(payload.get("name") or ""),
        source_type=str(payload.get("source_type") or default_source_type.value),
        url=str(payload.get("url") or ""),
        reliability=str(payload.get("reliability") or "medium"),
        authority_score=float(payload.get("authority_score", 0.5)),
        language=payload.get("language"),
        region=payload.get("region"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _raw_source_item_to_dict(item: RawSourceItem) -> dict[str, Any]:
    return {
        "source_item_id": item.source_item_id,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "source_type": item.source_type.value,
        "title": item.title,
        "url": item.url,
        "fetched_at": _dt(item.fetched_at),
        "published_at": _dt(item.published_at),
        "summary": item.summary,
        "raw_content": item.raw_content,
        "authors": list(item.authors),
        "tags": list(item.tags),
        "language": item.language,
        "metadata": dict(item.metadata),
    }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
