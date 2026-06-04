from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from business.foundation import SourceReliability, SourceType
from framework.tool.models import ToolDefinition
from framework.tool.registry import ToolRegistry


ARXIV_API_URL = "https://export.arxiv.org/api/query"
GITHUB_API_URL = "https://api.github.com"


@dataclass(frozen=True)
class ConnectorSourceDefinition:
    source_id: str
    name: str
    source_type: SourceType
    url: str
    reliability: SourceReliability = SourceReliability.HIGH
    authority_score: float = 0.9
    enabled: bool = True
    fetch_interval_seconds: int = 3600
    respect_robots: bool = True
    user_agent: str | None = None
    topics: list[str] = field(default_factory=list)
    category: str | None = None
    language: str | None = "en"
    region: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def register_arxiv_tools(registry: ToolRegistry, *, connector: Any | None = None) -> None:
    if connector is None:
        raise ValueError("arxiv connector is required")
    registry.register(
        ToolDefinition(
            name="arxiv.search_papers",
            description="Search arXiv papers through the configured arXiv connector.",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "source": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
        ),
        lambda args: _search_arxiv_papers(args, connector=connector),
    )


def register_github_tools(registry: ToolRegistry, *, connector: Any | None = None) -> None:
    if connector is None:
        raise ValueError("github connector is required")
    registry.register(
        ToolDefinition(
            name="github.fetch_releases",
            description="Fetch GitHub repository releases through the configured connector.",
            input_schema={
                "required": ["repository"],
                "properties": {
                    "repository": {"type": "string"},
                    "limit": {"type": "integer"},
                    "source": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
        ),
        lambda args: _fetch_github_releases(args, connector=connector),
    )
    registry.register(
        ToolDefinition(
            name="github.search_repositories",
            description="Search GitHub repositories through the configured connector.",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "sort": {
                        "type": "string",
                        "enum": ["stars", "forks", "help-wanted-issues", "updated"],
                    },
                    "order": {"type": "string", "enum": ["asc", "desc"]},
                    "source": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
        ),
        lambda args: _search_github_repositories(args, connector=connector),
    )


def _search_arxiv_papers(args: dict[str, Any], *, connector: Any) -> dict[str, Any]:
    query = _required_text(args.get("query"), "query")
    limit = _limit(args.get("limit"))
    source = _source_definition(args.get("source"), default_source_type=SourceType.ARXIV)
    items, errors = connector.fetch(source, query=query, limit=limit)
    return {
        "query": query,
        "limit": limit,
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
        "error_count": len(errors),
        "errors": [error.to_dict() for error in errors],
    }


def _fetch_github_releases(args: dict[str, Any], *, connector: Any) -> dict[str, Any]:
    repository = _required_text(args.get("repository"), "repository")
    limit = _limit(args.get("limit"))
    source = _source_definition(args.get("source"), default_source_type=SourceType.GITHUB)
    items, errors = connector.fetch_releases(source, repository=repository, limit=limit)
    return {
        "repository": repository,
        "limit": limit,
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
        "error_count": len(errors),
        "errors": [error.to_dict() for error in errors],
    }


def _search_github_repositories(args: dict[str, Any], *, connector: Any) -> dict[str, Any]:
    query = _required_text(args.get("query"), "query")
    limit = _limit(args.get("limit"))
    source = _source_definition(args.get("source"), default_source_type=SourceType.GITHUB)
    repositories, errors = connector.search_repositories(
        source,
        query=query,
        limit=limit,
        sort=str(args["sort"]) if args.get("sort") is not None else None,
        order=str(args["order"]) if args.get("order") is not None else None,
    )
    return {
        "query": query,
        "limit": limit,
        "repository_count": len(repositories),
        "repositories": [repository.to_dict() for repository in repositories],
        "error_count": len(errors),
        "errors": [error.to_dict() for error in errors],
    }


def _source_definition(payload: Any, *, default_source_type: SourceType) -> ConnectorSourceDefinition:
    default_url = ARXIV_API_URL if default_source_type == SourceType.ARXIV else GITHUB_API_URL
    default_name = "arXiv" if default_source_type == SourceType.ARXIV else "GitHub"
    default_authority = 0.95 if default_source_type == SourceType.ARXIV else 0.9
    if payload is None:
        return ConnectorSourceDefinition(
            source_id=default_source_type.value,
            name=default_name,
            source_type=default_source_type,
            url=default_url,
            reliability=SourceReliability.HIGH,
            authority_score=default_authority,
            language="en",
        )
    if not isinstance(payload, dict):
        raise ValueError("source must be an object")
    return ConnectorSourceDefinition(
        source_id=str(payload.get("source_id") or default_source_type.value),
        name=str(payload.get("name") or default_name),
        source_type=_source_type(payload.get("source_type") or default_source_type.value, default_source_type),
        url=str(payload.get("url") or default_url),
        reliability=_source_reliability(payload.get("reliability") or "high"),
        authority_score=float(payload.get("authority_score", default_authority)),
        language=payload.get("language"),
        region=payload.get("region"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _limit(value: Any) -> int:
    if value is None:
        return 10
    return max(1, min(int(value), 50))


def _raw_source_item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "source_item_id": item.source_item_id,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "source_type": _enum_value(item.source_type),
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


def _source_type(value: Any, fallback: SourceType) -> SourceType:
    try:
        return SourceType(str(getattr(value, "value", value)).strip().casefold())
    except ValueError:
        return fallback


def _source_reliability(value: Any) -> SourceReliability:
    try:
        return SourceReliability(str(getattr(value, "value", value)).strip().casefold())
    except ValueError:
        return SourceReliability.UNKNOWN


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


__all__ = [
    "ARXIV_API_URL",
    "GITHUB_API_URL",
    "ConnectorSourceDefinition",
    "register_arxiv_tools",
    "register_github_tools",
]
