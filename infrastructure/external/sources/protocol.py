from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from threading import Lock
from typing import Any, Protocol

from infrastructure.external.sources.models import RawSourceItem, SourceDefinition, SourceError, SourceFetchRequest, SourceFetchResult


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
        max_pending_results: int = 128,
    ) -> None:
        if max_pending_results < 1:
            raise ValueError("max_pending_results must be at least 1")
        self.connector = connector
        self.source_type = source_type
        self._fetch = fetch or connector.fetch
        self._max_pending_results = max_pending_results
        self._pending_items: dict[
            tuple[str, str],
            tuple[RawSourceItem, ...] | None,
        ] = {}
        self._pending_lock = Lock()

    @property
    def pending_result_count(self) -> int:
        with self._pending_lock:
            return len(self._pending_items)

    async def fetch(
        self,
        source: SourceDefinition,
        request: SourceFetchRequest,
        context: SourceFetchContext,
    ) -> SourceFetchResult:
        if request.source_id != source.source_id:
            raise ValueError("source request identity does not match source definition")
        key = (request.request_id, source.source_id)
        with self._pending_lock:
            if key in self._pending_items:
                raise ValueError("source fetch request is already pending")
            if len(self._pending_items) >= self._max_pending_results:
                raise RuntimeError("source connector pending result capacity reached")
            self._pending_items[key] = None

        kwargs: dict[str, Any] = {}
        if request.limit is not None:
            kwargs["limit"] = request.limit
        if request.query is not None and "query" in _callable_parameters(self._fetch):
            kwargs["query"] = request.query
        try:
            result = self._fetch(source, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except BaseException:
            with self._pending_lock:
                self._pending_items.pop(key, None)
            raise
        items, errors = result
        request_errors = [
            replace(
                error,
                metadata={**error.metadata, "request_id": request.request_id},
            )
            for error in errors
        ]
        with self._pending_lock:
            self._pending_items[key] = tuple(items)
        first_error = request_errors[0] if request_errors else None
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
                "error_count": len(request_errors),
                "source_errors": [error.to_dict() for error in request_errors],
            },
        )

    async def parse(
        self,
        source: SourceDefinition,
        fetch_result: SourceFetchResult,
        context: SourceFetchContext,
    ) -> list[RawSourceItem]:
        if fetch_result.source_id != source.source_id:
            raise ValueError("source fetch result identity does not match source definition")
        key = (fetch_result.request_id, source.source_id)
        with self._pending_lock:
            if key not in self._pending_items:
                raise ValueError("source fetch result is unavailable or already consumed")
            items = self._pending_items.pop(key)
        if items is None:
            raise RuntimeError("source fetch result is still pending")
        return list(items)

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
