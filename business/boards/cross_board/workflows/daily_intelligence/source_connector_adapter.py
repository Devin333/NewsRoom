from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from business.foundation.models.source import SourceDefinition, SourceError, SourceFetchRequest, SourceFetchResult
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_processing.error_taxonomy import classify_source_exception
from business.boards.cross_board.workflows.daily_intelligence.source_connector_ports import SourceFetchContext
from business.foundation.models.source_error_normalization import normalize_source_errors


def fetch_with_registered_connector(
    source_registry: SourceRegistry,
    source: SourceDefinition,
    *,
    request: dict[str, Any],
    fetch_request: SourceFetchRequest,
    profile: str,
) -> tuple[list[Any], list[SourceError], SourceFetchResult | None] | None:
    connector = registered_connector_for_source(source_registry, source)
    if connector is None:
        return None
    context = SourceFetchContext(
        profile=profile,
        topic=str(request.get("topic") or ""),
        metadata={
            "source_id": source.source_id,
            "limit": fetch_request.limit,
        },
    )
    try:
        if _is_protocol_connector(connector):
            return _invoke_protocol_connector(
                connector,
                source=source,
                fetch_request=fetch_request,
                context=context,
            )
        return _invoke_sync_connector(
            connector,
            source=source,
            fetch_request=fetch_request,
            context=context,
        )
    except Exception as exc:
        return [], [_registered_connector_error(source, exc)], None


def registered_connector_for_source(source_registry: SourceRegistry, source: SourceDefinition) -> Any | None:
    try:
        return source_registry.get_connector(source.source_type)
    except KeyError:
        return None


def connector_display_name(connector: Any) -> str:
    wrapped_connector = getattr(connector, "connector", None)
    if wrapped_connector is not None:
        return type(wrapped_connector).__name__
    return type(connector).__name__


def _is_protocol_connector(connector: Any) -> bool:
    fetch = getattr(connector, "fetch", None)
    parse = getattr(connector, "parse", None)
    if not callable(fetch) or not callable(parse):
        return False
    parameters = _callable_parameters(fetch)
    return "request" in parameters and "context" in parameters


def _invoke_protocol_connector(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> tuple[list[Any], list[SourceError], SourceFetchResult]:
    fetch_result = _coerce_source_fetch_result(
        _run_maybe_awaitable(connector.fetch(source, fetch_request, context))
    )
    parsed_items = _run_maybe_awaitable(connector.parse(source, fetch_result, context))
    items = list(parsed_items or [])
    errors = _connector_errors(
        connector,
        source=source,
        fetch_request=fetch_request,
        fetch_result=fetch_result,
    )
    return items, errors, fetch_result


def _invoke_sync_connector(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> tuple[list[Any], list[SourceError], SourceFetchResult | None]:
    fetch = getattr(connector, "fetch", None)
    if not callable(fetch):
        raise TypeError("registered source connector must expose a fetch method")
    kwargs = _registered_fetch_kwargs(fetch, fetch_request=fetch_request, context=context)
    result = _run_maybe_awaitable(fetch(source, **kwargs))
    fetch_result = _coerce_source_fetch_result_or_none(result)
    if fetch_result is not None:
        parse = getattr(connector, "parse", None)
        if not callable(parse):
            errors = _connector_errors(
                connector,
                source=source,
                fetch_request=fetch_request,
                fetch_result=fetch_result,
            )
            return [], errors, fetch_result
        parsed_items = _run_maybe_awaitable(parse(source, fetch_result, context))
        items = list(parsed_items or [])
        errors = _connector_errors(
            connector,
            source=source,
            fetch_request=fetch_request,
            fetch_result=fetch_result,
        )
        return items, errors, fetch_result
    try:
        items, errors = result
    except (TypeError, ValueError) as exc:
        raise TypeError("registered source connector fetch must return (items, errors)") from exc
    return list(items or []), normalize_source_errors(
        errors or [],
        context="registered source connector errors",
    ), None


def _registered_fetch_kwargs(
    fetch: Any,
    *,
    fetch_request: SourceFetchRequest,
    context: SourceFetchContext,
) -> dict[str, Any]:
    parameters = _callable_parameters(fetch)
    kwargs: dict[str, Any] = {}
    if "limit" in parameters and fetch_request.limit is not None:
        kwargs["limit"] = fetch_request.limit
    if "query" in parameters and fetch_request.query is not None:
        kwargs["query"] = fetch_request.query
    if "request" in parameters:
        kwargs["request"] = fetch_request
    if "context" in parameters:
        kwargs["context"] = context
    return kwargs


def _connector_errors(
    connector: Any,
    *,
    source: SourceDefinition,
    fetch_request: SourceFetchRequest,
    fetch_result: SourceFetchResult,
) -> list[SourceError]:
    errors_for = getattr(connector, "errors_for", None)
    if callable(errors_for):
        errors = _run_maybe_awaitable(errors_for(fetch_request.request_id))
        return normalize_source_errors(
            errors or [],
            context="registered source connector errors",
        )
    if fetch_result.error_type is None:
        return []
    return [
        SourceError(
            source_id=source.source_id,
            source_name=source.name,
            error_type=fetch_result.error_type,
            error_message=fetch_result.error_message or fetch_result.error_type,
            url=source.url,
            metadata={
                "phase": "fetch",
                "request_id": fetch_request.request_id,
                "connector_name": connector_display_name(connector),
            },
        )
    ]


def _run_maybe_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value if isinstance(value, Coroutine) else _await_value(value))
    raise RuntimeError(
        "registered source connector returned an awaitable while an event loop is running"
    )


async def _await_value(value: Any) -> Any:
    return await value


def _callable_parameters(value: Any) -> set[str]:
    try:
        return set(inspect.signature(value).parameters)
    except (TypeError, ValueError):
        return set()


def _coerce_source_fetch_result_or_none(value: Any) -> SourceFetchResult | None:
    if isinstance(value, SourceFetchResult):
        return value
    if _SourceFetchResultView.can_project(value):
        return _coerce_source_fetch_result(value)
    return None


def _coerce_source_fetch_result(value: Any) -> SourceFetchResult:
    if isinstance(value, SourceFetchResult):
        return value
    view = _SourceFetchResultView.from_value(value)
    if view is None:
        raise TypeError("registered source connector fetch must return SourceFetchResult")
    kwargs: dict[str, Any] = {
        "request_id": view.request_id,
        "source_id": view.source_id,
        "success": view.success,
        "status_code": view.status_code,
        "content_type": view.content_type,
        "content_bytes": view.content_bytes,
        "latency_ms": view.latency_ms,
        "raw_artifact_ref": view.raw_artifact_ref,
        "error_type": view.error_type,
        "error_message": view.error_message,
        "skipped": view.skipped,
        "skip_reason": view.skip_reason,
        "metadata": dict(view.metadata),
    }
    if view.fetched_at is not None:
        kwargs["fetched_at"] = view.fetched_at
    return SourceFetchResult(**kwargs)


@dataclass(frozen=True)
class _SourceFetchResultView:
    request_id: str
    source_id: str
    success: bool
    status_code: int | None = None
    content_type: str | None = None
    content_bytes: int | None = None
    latency_ms: float | None = None
    raw_artifact_ref: Any = None
    error_type: str | None = None
    error_message: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    fetched_at: Any = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def can_project(cls, value: Any) -> bool:
        return cls.from_value(value) is not None

    @classmethod
    def from_value(cls, value: Any) -> "_SourceFetchResultView | None":
        if not _has_fields(value, ("request_id", "source_id", "success")):
            return None
        return cls(
            request_id=str(getattr(value, "request_id")),
            source_id=str(getattr(value, "source_id")),
            success=bool(getattr(value, "success")),
            status_code=getattr(value, "status_code", None),
            content_type=getattr(value, "content_type", None),
            content_bytes=getattr(value, "content_bytes", None),
            latency_ms=getattr(value, "latency_ms", None),
            raw_artifact_ref=getattr(value, "raw_artifact_ref", None),
            error_type=getattr(value, "error_type", None),
            error_message=getattr(value, "error_message", None),
            skipped=bool(getattr(value, "skipped", False)),
            skip_reason=getattr(value, "skip_reason", None),
            fetched_at=getattr(value, "fetched_at", None),
            metadata=_metadata_dict(getattr(value, "metadata", None)),
        )


def _has_fields(value: Any, field_names: tuple[str, ...]) -> bool:
    return all(hasattr(value, field_name) for field_name in field_names)


def _metadata_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _registered_connector_error(source: SourceDefinition, exc: Exception) -> SourceError:
    classification = classify_source_exception(exc, phase="fetch")
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=classification.error_type,
        error_message=str(exc),
        url=source.url,
        retryable=classification.retryable,
        metadata={
            "phase": "fetch",
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "registered_connector": True,
            "original_exception_type": type(exc).__name__,
        },
    )
