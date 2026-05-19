from __future__ import annotations

from datetime import datetime
from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.sources import RawSourceItem, SourceDefinition
from sources.connectors import ARXIV_API_URL, ArxivConnector


def register_arxiv_tools(
    registry: ToolRegistry,
    *,
    connector: ArxivConnector | None = None,
) -> None:
    connector = connector or ArxivConnector()
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
        lambda args: _search_papers(args, connector=connector),
    )


def _search_papers(args: dict[str, Any], *, connector: ArxivConnector) -> dict[str, Any]:
    query = str(args["query"]).strip()
    if not query:
        raise ValueError("query is required")
    limit = _limit(args.get("limit"))
    source = _source_definition(args.get("source"))
    items, errors = connector.fetch(source, query=query, limit=limit)
    return {
        "query": query,
        "limit": limit,
        "item_count": len(items),
        "items": [_raw_source_item_to_dict(item) for item in items],
        "error_count": len(errors),
        "errors": [error.to_dict() for error in errors],
    }


def _source_definition(payload: Any) -> SourceDefinition:
    if payload is None:
        return SourceDefinition(
            source_id="arxiv",
            name="arXiv",
            source_type="arxiv",
            url=ARXIV_API_URL,
            reliability="high",
            authority_score=0.95,
            language="en",
        )
    if not isinstance(payload, dict):
        raise ValueError("source must be an object")
    return SourceDefinition(
        source_id=str(payload.get("source_id") or "arxiv"),
        name=str(payload.get("name") or "arXiv"),
        source_type=str(payload.get("source_type") or "arxiv"),
        url=str(payload.get("url") or ARXIV_API_URL),
        reliability=str(payload.get("reliability") or "high"),
        authority_score=float(payload.get("authority_score", 0.95)),
        language=payload.get("language"),
        region=payload.get("region"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _limit(value: Any) -> int:
    if value is None:
        return 10
    return max(1, min(int(value), 50))


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
