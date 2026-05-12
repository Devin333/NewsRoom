from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceReliability, SourceType
from sources import SourceRegistry
from sources.connectors import (
    FeedConnector,
    HtmlConnector,
    ManualConnector,
    SourceFetchPolicy,
    effective_fetch_policy,
    ensure_robots_allowed,
    open_request_with_fetch_policy,
    run_with_fetch_retries,
)
from sources.health import BasicSourceHealthManager
from sources.processing.normalize import canonicalize_url


FetchText = Callable[[str], str]


def register_source_tools(
    registry: ToolRegistry,
    *,
    fetch_text: FetchText | None = None,
    fetch_policy: SourceFetchPolicy | None = None,
    allowed_domains: list[str] | None = None,
    health_manager: BasicSourceHealthManager | None = None,
    source_registry: SourceRegistry | None = None,
) -> None:
    fetch_policy = fetch_policy or SourceFetchPolicy()
    allowed_domain_tuple = _allowed_domains(allowed_domains)
    health_manager = health_manager or BasicSourceHealthManager()
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
                    "max_redirects": {"type": "integer"},
                    "respect_robots": {"type": "boolean"},
                    "user_agent": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            timeout_seconds=fetch_policy.timeout_seconds + 1.0,
            max_result_bytes=1_100_000,
        ),
        lambda args: _fetch_url(
            args,
            default_policy=fetch_policy,
            fetch_text=fetch_text,
            allowed_domains=allowed_domain_tuple,
        ),
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
            description="Extract raw source items from fetched RSS, Atom, or HTML content.",
            input_schema={
                "required": ["source", "content"],
                "properties": {
                    "source": {"type": "object"},
                    "content": {"type": ["string", "array"]},
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
            name="source.fetch_official_blog",
            description="Fetch and parse a marked official blog RSS, Atom, or HTML source.",
            input_schema={
                "required": [],
                "properties": {
                    "source": {"type": "object"},
                    "source_id": {"type": "string"},
                    "topic": {"type": "string"},
                    "language": {"type": "string"},
                    "region": {"type": "string"},
                    "limit": {"type": "integer"},
                    "timeout_seconds": {"type": "number"},
                    "max_bytes": {"type": "integer"},
                    "max_redirects": {"type": "integer"},
                    "respect_robots": {"type": "boolean"},
                    "user_agent": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            timeout_seconds=fetch_policy.timeout_seconds + 1.0,
            max_result_bytes=1_000_000,
            metadata={"source_kind": "official_blog"},
        ),
        lambda args: _fetch_official_blog(
            args,
            source_registry=source_registry,
            default_policy=fetch_policy,
            fetch_text=fetch_text,
            allowed_domains=allowed_domain_tuple,
        ),
    )
    registry.register(
        ToolDefinition(
            name="source.check_health",
            description="Read current source health for a source id.",
            input_schema={
                "required": [],
                "properties": {
                    "source_id": {"type": "string"},
                    "source": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: {"health": _source_health(args, health_manager=health_manager).to_dict()},
    )
    registry.register(
        ToolDefinition(
            name="source.probe",
            description="Probe a source URL and update in-memory source health.",
            input_schema={
                "required": ["source"],
                "properties": {
                    "source": {"type": "object"},
                    "timeout_seconds": {"type": "number"},
                    "max_bytes": {"type": "integer"},
                    "max_redirects": {"type": "integer"},
                    "respect_robots": {"type": "boolean"},
                    "user_agent": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=False,
            timeout_seconds=fetch_policy.timeout_seconds + 1.0,
            max_result_bytes=100_000,
            metadata={"updates_source_health": True},
        ),
        lambda args: _probe_source(
            args,
            default_policy=fetch_policy,
            fetch_text=fetch_text,
            allowed_domains=allowed_domain_tuple,
            health_manager=health_manager,
        ),
    )
    if source_registry is not None:
        registry.register(
            ToolDefinition(
                name="source.search",
                description="Search configured sources from SourceRegistry.",
                input_schema={
                    "required": [],
                    "properties": {
                        "query": {"type": "string"},
                        "enabled_only": {"type": "boolean"},
                        "language": {"type": "string"},
                        "region": {"type": "string"},
                        "reliability": {"type": "string"},
                        "source_type": {"type": "string"},
                        "fallback_to_enabled": {"type": "boolean"},
                        "limit": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
                side_effect="read_only",
                concurrency_safe=True,
            ),
            lambda args: _search_sources(args, source_registry=source_registry),
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
            name="source.extract_html",
            description="Extract visible text and metadata from fetched HTML content.",
            input_schema={
                "required": ["source", "html"],
                "properties": {
                    "source": {"type": "object"},
                    "html": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        _parse_html,
    )
    registry.register(
        ToolDefinition(
            name="source.extract_manual",
            description="Extract raw source items from human-curated manual source records.",
            input_schema={
                "required": ["source", "records"],
                "properties": {
                    "source": {"type": "object"},
                    "records": {"type": "array"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        _parse_manual,
    )
    registry.register(
        ToolDefinition(
            name="source.normalize_url",
            description="Canonicalize a source URL and strip known tracking parameters.",
            input_schema={
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "base_url": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: {
            "canonical_url": canonicalize_url(
                str(args["url"]),
                base_url=str(args["base_url"]) if args.get("base_url") is not None else None,
            )
        },
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
    source = _source_definition(args["source"], default_source_type=SourceType.RSS)
    if source.source_type == SourceType.HTML:
        return _parse_html(
            {"source": args["source"], "html": args["content"], "limit": args.get("limit")}
        )
    if source.source_type == SourceType.MANUAL:
        return _parse_manual(
            {"source": args["source"], "records": args["content"], "limit": args.get("limit")}
        )
    return _parse_feed(
        {"source": args["source"], "xml": args["content"], "limit": args.get("limit")},
        default_source_type=SourceType.RSS,
    )


def _parse_html(args: dict[str, Any]) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=SourceType.HTML)
    if source.source_type != SourceType.HTML:
        raise ValueError("source.extract_html requires source_type=html")
    limit = args.get("limit")
    items = HtmlConnector().parse(
        source,
        str(args["html"]),
        limit=int(limit) if limit is not None else None,
    )
    return {
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
    }


def _parse_manual(args: dict[str, Any]) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=SourceType.MANUAL)
    if source.source_type != SourceType.MANUAL:
        raise ValueError("source.extract_manual requires source_type=manual")
    records = args["records"]
    if not isinstance(records, list):
        raise ValueError("source.extract_manual records must be an array")
    items, errors = ManualConnector().fetch(
        source,
        records=records,
        limit=_optional_limit(args.get("limit")),
    )
    return {
        "item_count": len(items),
        "error_count": len(errors),
        "items": [_raw_source_item_to_dict(item) for item in items],
        "errors": [error.to_dict() for error in errors],
    }


def _fetch_official_blog(
    args: dict[str, Any],
    *,
    source_registry: SourceRegistry | None,
    default_policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
    allowed_domains: tuple[str, ...],
) -> dict[str, Any]:
    source = _official_blog_source(args, source_registry=source_registry)
    _ensure_official_blog(source)
    _ensure_official_blog_source_type(source)
    _ensure_http_url(source.url)
    _ensure_allowed_domain(source.url, allowed_domains)
    policy = effective_fetch_policy(_fetch_policy(args, default_policy), source)
    connector = _official_blog_connector(source, fetch_text=fetch_text, policy=policy)
    items, errors = connector.fetch(source, limit=_optional_limit(args.get("limit")))
    return {
        "source": _source_definition_to_dict(source),
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
        "error_count": len(errors),
        "errors": [error.to_dict() for error in errors],
    }


def _fetch_url(
    args: dict[str, Any],
    *,
    default_policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
    allowed_domains: tuple[str, ...],
) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=SourceType.RSS)
    _ensure_http_url(source.url)
    _ensure_allowed_domain(source.url, allowed_domains)
    policy = effective_fetch_policy(_fetch_policy(args, default_policy), source)
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
            "max_redirects": policy.max_redirects,
            "respect_robots": policy.respect_robots,
            "user_agent": policy.user_agent,
        },
    }


def _probe_source(
    args: dict[str, Any],
    *,
    default_policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
    allowed_domains: tuple[str, ...],
    health_manager: BasicSourceHealthManager,
) -> dict[str, Any]:
    source = _source_definition(args["source"], default_source_type=SourceType.RSS)
    _ensure_http_url(source.url)
    _ensure_allowed_domain(source.url, allowed_domains)
    policy = effective_fetch_policy(_fetch_policy(args, default_policy), source)
    try:
        content, status_code, content_type = _fetch_text(source.url, policy, fetch_text)
    except Exception as exc:
        error = SourceError(
            source_id=source.source_id,
            source_name=source.name,
            error_type=type(exc).__name__,
            error_message=str(exc),
            url=source.url,
            metadata={"tool": "source.probe"},
        )
        health = health_manager.record_failure(
            source.source_id,
            error,
            source_name=source.name,
            url=source.url,
        )
        return {
            "ok": False,
            "source_id": source.source_id,
            "url": source.url,
            "canonical_url": canonicalize_url(source.url),
            "error": error.to_dict(),
            "health": health.to_dict(),
        }

    health = health_manager.record_success(
        source.source_id,
        source_name=source.name,
        url=source.url,
    )
    return {
        "ok": True,
        "source_id": source.source_id,
        "url": source.url,
        "canonical_url": canonicalize_url(source.url),
        "status_code": status_code,
        "content_type": content_type,
        "content_bytes": len(content.encode("utf-8")),
        "health": health.to_dict(),
    }


def _search_sources(
    args: dict[str, Any],
    *,
    source_registry: SourceRegistry,
) -> dict[str, Any]:
    enabled_only = bool(args.get("enabled_only", True))
    language = args.get("language")
    region = args.get("region")
    reliability = args.get("reliability")
    source_type = args.get("source_type")
    limit = _optional_limit(args.get("limit"))
    query = str(args.get("query") or "").strip()
    if query:
        sources = source_registry.select_sources(
            topic=query,
            enabled_only=enabled_only,
            language=str(language) if language is not None else None,
            region=str(region) if region is not None else None,
            reliability=str(reliability) if reliability is not None else None,
            fallback_to_enabled=bool(args.get("fallback_to_enabled", True)),
        )
    else:
        sources = source_registry.list_sources(enabled_only=enabled_only)
        if language is not None:
            sources = [source for source in sources if source.language == str(language)]
        if region is not None:
            sources = [source for source in sources if source.region == str(region)]
        if reliability is not None:
            expected_reliability = SourceReliability(str(reliability))
            sources = [source for source in sources if source.reliability == expected_reliability]
    if source_type is not None:
        expected_type = SourceType(str(source_type))
        sources = [source for source in sources if source.source_type == expected_type]
    if limit is not None:
        sources = sources[:limit]
    return {
        "query": query or None,
        "source_count": len(sources),
        "sources": [_source_definition_to_dict(source) for source in sources],
    }


def _fetch_policy(args: dict[str, Any], default_policy: SourceFetchPolicy) -> SourceFetchPolicy:
    timeout_seconds = float(args.get("timeout_seconds", default_policy.timeout_seconds))
    max_bytes = int(args.get("max_bytes", default_policy.max_bytes))
    max_redirects = int(args.get("max_redirects", default_policy.max_redirects))
    respect_robots = _optional_bool(args.get("respect_robots"), default_policy.respect_robots)
    if max_bytes > 1_000_000:
        raise ValueError("max_bytes must not exceed 1000000 for source.fetch_url")
    return SourceFetchPolicy(
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        respect_robots=respect_robots,
        user_agent=str(args.get("user_agent") or default_policy.user_agent),
        rate_limit_per_domain_per_minute=default_policy.rate_limit_per_domain_per_minute,
        retry_times=default_policy.retry_times,
        retry_on_status_codes=default_policy.retry_on_status_codes,
    )


def _fetch_text(
    url: str,
    policy: SourceFetchPolicy,
    fetch_text: FetchText | None,
) -> tuple[str, int | None, str | None]:
    if fetch_text is not None:
        return run_with_fetch_retries(lambda: (fetch_text(url), None, None), policy)
    return run_with_fetch_retries(lambda: _default_fetch_text(url, policy), policy)


def _default_fetch_text(url: str, policy: SourceFetchPolicy) -> tuple[str, int | None, str | None]:
    ensure_robots_allowed(url, policy)
    request = Request(url, headers={"User-Agent": policy.user_agent})
    with open_request_with_fetch_policy(request, policy) as response:
        body = response.read(policy.max_bytes + 1)
        status_code = getattr(response, "status", None)
        headers = getattr(response, "headers", None)
        content_type = headers.get_content_type() if headers is not None else None
    if len(body) > policy.max_bytes:
        raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
    return body.decode("utf-8", errors="replace"), status_code, content_type


def _policy_fetch_text(
    fetch_text: FetchText | None,
    policy: SourceFetchPolicy,
) -> FetchText | None:
    if fetch_text is None:
        return None

    def wrapped(url: str) -> str:
        content = fetch_text(url)
        if len(content.encode("utf-8")) > policy.max_bytes:
            raise ValueError(f"source response exceeds max_bytes: {policy.max_bytes}")
        return content

    return wrapped


def _ensure_http_url(url: str) -> None:
    scheme = urlsplit(url).scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError(f"source.fetch_url only supports http and https URLs: {url}")


def _allowed_domains(allowed_domains: list[str] | None) -> tuple[str, ...]:
    return tuple(
        domain.strip().casefold().lstrip(".")
        for domain in allowed_domains or []
        if domain.strip()
    )


def _ensure_allowed_domain(url: str, allowed_domains: tuple[str, ...]) -> None:
    if not allowed_domains:
        return
    host = (urlsplit(url).hostname or "").casefold()
    if any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        return
    raise ValueError(f"source.fetch_url host is not in allowed domains: {host}")


def _official_blog_source(
    args: dict[str, Any],
    *,
    source_registry: SourceRegistry | None,
) -> SourceDefinition:
    source_payload = args.get("source")
    if source_payload is not None:
        return _source_definition(source_payload, default_source_type=SourceType.RSS)
    source_id = args.get("source_id")
    if source_id:
        if source_registry is None:
            raise ValueError("source_registry is required to resolve source_id")
        return source_registry.get(str(source_id))
    topic = str(args.get("topic") or "").strip()
    if topic:
        if source_registry is None:
            raise ValueError("source_registry is required to resolve topic")
        sources = source_registry.select_sources(
            topic=topic,
            enabled_only=True,
            language=str(args["language"]) if args.get("language") is not None else None,
            region=str(args["region"]) if args.get("region") is not None else None,
            fallback_to_enabled=True,
        )
        for source in sources:
            if _is_official_blog(source):
                return source
        raise ValueError(f"no official blog source matched topic: {topic}")
    raise ValueError("source, source_id, or topic is required")


def _ensure_official_blog(source: SourceDefinition) -> None:
    if not _is_official_blog(source):
        raise ValueError(f"source is not marked as an official blog: {source.source_id}")


def _is_official_blog(source: SourceDefinition) -> bool:
    metadata = source.metadata
    if _truthy(metadata.get("official_blog")) or _truthy(metadata.get("official")):
        return True
    for key in ["source_kind", "kind", "category"]:
        marker = str(metadata.get(key) or "").casefold().replace("-", "_").replace(" ", "_")
        if marker == "official_blog":
            return True
    return False


def _ensure_official_blog_source_type(source: SourceDefinition) -> None:
    if source.source_type not in {SourceType.RSS, SourceType.ATOM, SourceType.HTML}:
        raise ValueError(f"official blog source must be rss, atom, or html: {source.source_id}")


def _official_blog_connector(
    source: SourceDefinition,
    *,
    fetch_text: FetchText | None,
    policy: SourceFetchPolicy,
) -> FeedConnector | HtmlConnector:
    if source.source_type == SourceType.HTML:
        return HtmlConnector(
            fetch_text=_policy_fetch_text(fetch_text, policy),
            fetch_policy=policy,
        )
    return FeedConnector(
        fetch_text=_policy_fetch_text(fetch_text, policy),
        fetch_policy=policy,
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _optional_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return _truthy(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
        respect_robots=_optional_bool(payload.get("respect_robots"), True),
        language=payload.get("language"),
        region=payload.get("region"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _source_id(args: dict[str, Any]) -> str:
    source_id = args.get("source_id")
    if source_id:
        return str(source_id)
    source = args.get("source")
    if isinstance(source, dict) and source.get("source_id"):
        return str(source["source_id"])
    raise ValueError("source_id or source.source_id is required")


def _source_health(args: dict[str, Any], *, health_manager: BasicSourceHealthManager):
    source = args.get("source")
    if isinstance(source, dict):
        source_id = str(source.get("source_id") or "")
        if not source_id:
            raise ValueError("source.source_id is required")
        return health_manager.get(
            source_id,
            source_name=_optional_text(source.get("name")),
            url=_optional_text(source.get("url")),
        )
    return health_manager.get(_source_id(args))


def _optional_limit(value: Any) -> int | None:
    if value is None:
        return None
    return max(1, min(int(value), 100))


def _source_definition_to_dict(source: SourceDefinition) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "name": source.name,
        "source_type": source.source_type.value,
        "url": source.url,
        "reliability": source.reliability.value,
        "authority_score": source.authority_score,
        "enabled": source.enabled,
        "respect_robots": source.respect_robots,
        "topics": list(source.topics),
        "language": source.language,
        "region": source.region,
        "metadata": dict(source.metadata),
    }


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
