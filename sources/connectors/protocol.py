from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceFetchRequest, SourceFetchResult


@dataclass(frozen=True)
class SourceFetchContext:
    run_id: str | None = None
    profile: str | None = None
    topic: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceConnector(Protocol):
    source_type: str

    async def fetch(
        self,
        source: SourceDefinition,
        request: SourceFetchRequest,
        context: SourceFetchContext,
    ) -> SourceFetchResult: ...

    async def parse(
        self,
        source: SourceDefinition,
        fetch_result: SourceFetchResult,
        context: SourceFetchContext,
    ) -> list[RawSourceItem]: ...


SyncFetch = Callable[..., tuple[list[RawSourceItem], list[SourceError]]]


class SyncSourceConnectorAdapter:
    def __init__(
        self,
        connector: Any,
        *,
        source_type: str,
        fetch: SyncFetch | None = None,
    ) -> None:
        self.connector = connector
        self.source_type = source_type
        self._fetch = fetch or connector.fetch
        self._items_by_request_id: dict[str, list[RawSourceItem]] = {}
        self._errors_by_request_id: dict[str, list[SourceError]] = {}

    async def fetch(
        self,
        source: SourceDefinition,
        request: SourceFetchRequest,
        context: SourceFetchContext,
    ) -> SourceFetchResult:
        kwargs: dict[str, Any] = {}
        if request.limit is not None:
            kwargs["limit"] = request.limit
        if request.query is not None and "query" in _callable_parameters(self._fetch):
            kwargs["query"] = request.query
        result = self._fetch(source, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        items, errors = result
        self._items_by_request_id[request.request_id] = list(items)
        self._errors_by_request_id[request.request_id] = list(errors)
        first_error = errors[0] if errors else None
        return SourceFetchResult(
            request_id=request.request_id,
            source_id=source.source_id,
            success=bool(items),
            content_bytes=_raw_content_bytes(items),
            error_type=first_error.error_type if first_error else None,
            error_message=first_error.error_message if first_error else None,
            metadata={
                "source_type": source.source_type.value,
                "connector_name": type(self.connector).__name__,
                "context": {
                    "run_id": context.run_id,
                    "profile": context.profile,
                    "topic": context.topic,
                },
                "item_count": len(items),
                "error_count": len(errors),
            },
        )

    async def parse(
        self,
        source: SourceDefinition,
        fetch_result: SourceFetchResult,
        context: SourceFetchContext,
    ) -> list[RawSourceItem]:
        return list(self._items_by_request_id.get(fetch_result.request_id, []))

    def errors_for(self, request_id: str) -> list[SourceError]:
        return list(self._errors_by_request_id.get(request_id, []))


def _raw_content_bytes(items: list[RawSourceItem]) -> int | None:
    total = 0
    found = False
    for item in items:
        if item.raw_content is None:
            continue
        found = True
        total += len(item.raw_content.encode("utf-8"))
    return total if found else None


def _callable_parameters(value: Callable[..., Any]) -> set[str]:
    try:
        return set(inspect.signature(value).parameters)
    except (TypeError, ValueError):
        return set()
