from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.sources import RawSourceItem, SourceDefinition, SourceType
from sources.connectors import FeedConnector, SourceFetchPolicy
from sources.processing.normalize import canonicalize_url


FetchText = Callable[[str], str]


def register_source_tools(
    registry: ToolRegistry,
    *,
    fetch_text: FetchText | None = None,
    fetch_policy: SourceFetchPolicy | None = None,
) -> None:
    fetch_policy = fetch_policy or SourceFetchPolicy()
    registry.register(
        ToolDefinition(
            name="source.fetch_url",
            description="Fetch text content for a configured source URL with source fetch policy.",
            input_schema={
                "required": ["source"],
                "properties": {
                    "source": {"type": "object"},
                    "timeout_seconds": {"type": "number"},
                    "max_bytes": {"type": "integer"},
                    "user_agent": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            timeout_seconds=fetch_policy.timeout_seconds + 1.0,
            max_result_bytes=1_100_000,
        ),
        lambda args: _fetch_url(args, default_policy=fetch_policy, fetch_text=fetch_text),
    )
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
            name="source.extract_items",
            description="Extract raw source items from fetched RSS or Atom content.",
            input_schema={
                "required": ["source", "content"],
                "properties": {
                    "source": {"type": "object"},
                    "content": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        _extract_items,
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


def _extract_items(args: dict[str, Any]) -> dict[str, Any]:
    return _parse_feed(
        {"source": args["source"], "xml": args["content"], "limit": args.get("limit")},
        default_source_type=SourceType.RSS,
    )


def _fetch_url(
    args: dict[str, Any],
    *,
    default_policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=SourceType.RSS)
    _ensure_http_url(source.url)
    policy = _fetch_policy(args, default_policy)
    content, status_code, content_type = _fetch_text(source.url, policy, fetch_text)
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > policy.max_bytes:
        raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "source_type": source.source_type.value,
        "url": source.url,
        "canonical_url": canonicalize_url(source.url),
        "content": content,
        "content_bytes": content_bytes,
        "status_code": status_code,
        "content_type": content_type,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "fetch_policy": {
            "timeout_seconds": policy.timeout_seconds,
            "max_bytes": policy.max_bytes,
            "user_agent": policy.user_agent,
        },
    }


def _fetch_policy(args: dict[str, Any], default_policy: SourceFetchPolicy) -> SourceFetchPolicy:
    timeout_seconds = float(args.get("timeout_seconds", default_policy.timeout_seconds))
    max_bytes = int(args.get("max_bytes", default_policy.max_bytes))
    if max_bytes > 1_000_000:
        raise ValueError("max_bytes must not exceed 1000000 for source.fetch_url")
    return SourceFetchPolicy(
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        user_agent=str(args.get("user_agent") or default_policy.user_agent),
    )


def _fetch_text(
    url: str,
    policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
) -> tuple[str, int | None, str | None]:
    if fetch_text is not None:
        return fetch_text(url), None, None
    request = Request(url, headers={"User-Agent": policy.user_agent})
    with urlopen(request, timeout=policy.timeout_seconds) as response:
        body = response.read(policy.max_bytes + 1)
        status_code = getattr(response, "status", None)
        headers = getattr(response, "headers", None)
        content_type = headers.get_content_type() if headers is not None else None
    if len(body) > policy.max_bytes:
        raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
    return body.decode("utf-8", errors="replace"), status_code, content_type


def _ensure_http_url(url: str) -> None:
    scheme = urlsplit(url).scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError(f"source.fetch_url only supports http and https URLs: {url}")


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
