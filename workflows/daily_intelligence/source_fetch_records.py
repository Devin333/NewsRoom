from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any

from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourceType,
)
from sources.connectors import SourceFetchPolicy
from sources.connectors.diagnostics import response_metadata_from_observations
from workflows.daily_intelligence.source_connector_names import source_connector_name


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def dt(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def source_fetch_request_id(existing: list[SourceFetchRequest], source: SourceDefinition) -> str:
    return f"source-fetch-{len(existing) + 1:04d}-{source.source_id}"


def source_fetch_request(
    source: SourceDefinition,
    *,
    request_id: str,
    request: dict[str, Any],
    limit: int,
    profile: str,
    fetch_policy: SourceFetchPolicy | None = None,
    connector_name: str | None = None,
) -> SourceFetchRequest:
    query = None
    if source.source_type == SourceType.ARXIV:
        query = str(source.metadata.get("query") or request.get("topic") or "")
    user_agent = fetch_policy.user_agent if fetch_policy is not None else source.user_agent
    return SourceFetchRequest(
        request_id=request_id,
        source_id=source.source_id,
        source_type=source.source_type,
        url=source.url,
        query=query,
        timeout_seconds=fetch_policy.timeout_seconds if fetch_policy is not None else 15,
        max_bytes=fetch_policy.max_bytes if fetch_policy is not None else 1_000_000,
        max_redirects=fetch_policy.max_redirects if fetch_policy is not None else 3,
        user_agent=user_agent,
        headers={"User-Agent": user_agent} if user_agent else {},
        limit=limit,
        metadata={
            "profile": profile,
            "topic": request.get("topic"),
            "source_name": source.name,
            "reliability": source.reliability.value,
            "authority_score": source.authority_score,
            "fetch_interval_seconds": source.fetch_interval_seconds,
            "respect_robots": source.respect_robots,
            "connector_name": connector_name or source_connector_name(source),
            **(_fetch_policy_metadata(fetch_policy) if fetch_policy is not None else {}),
        },
    )


def final_source_fetch_result(
    *,
    source: SourceDefinition,
    request_id: str,
    connector_fetch_result: SourceFetchResult | None,
    success: bool,
    latency_ms: float,
    items: list[Any],
    errors: list[SourceError],
) -> SourceFetchResult:
    fallback = source_fetch_result(
        source,
        request_id=request_id,
        success=success,
        latency_ms=latency_ms,
        items=items,
        errors=errors,
    )
    if connector_fetch_result is None:
        return fallback
    metadata = dict(fallback.metadata)
    metadata.update(dict(connector_fetch_result.metadata))
    metadata["item_count"] = len(items)
    metadata["error_count"] = len(errors)
    first_error = errors[0] if errors else None
    return replace(
        connector_fetch_result,
        request_id=request_id,
        source_id=source.source_id,
        success=success,
        status_code=connector_fetch_result.status_code or fallback.status_code,
        content_type=connector_fetch_result.content_type or fallback.content_type,
        content_bytes=(
            connector_fetch_result.content_bytes
            if connector_fetch_result.content_bytes is not None
            else fallback.content_bytes
        ),
        latency_ms=(
            connector_fetch_result.latency_ms
            if connector_fetch_result.latency_ms is not None
            else fallback.latency_ms
        ),
        error_type=connector_fetch_result.error_type
        or (first_error.error_type if first_error else None),
        error_message=connector_fetch_result.error_message
        or (first_error.error_message if first_error else None),
        metadata=metadata,
    )


def source_fetch_result(
    source: SourceDefinition,
    *,
    request_id: str,
    success: bool,
    latency_ms: float,
    items: list[Any],
    errors: list[SourceError],
    skipped: bool = False,
    skip_reason: str | None = None,
) -> SourceFetchResult:
    first_error = errors[0] if errors else None
    response_metadata = response_metadata_from_observations(items=items, errors=errors)
    metadata: dict[str, Any] = {
        "source_type": source.source_type.value,
        "url": source.url,
        "item_count": len(items),
        "error_count": len(errors),
    }
    if response_metadata is not None:
        metadata["response_url"] = response_metadata.get("url")
        metadata["response_headers"] = response_metadata.get("headers", {})
        metadata["fetch_response"] = response_metadata
    return SourceFetchResult(
        request_id=request_id,
        source_id=source.source_id,
        success=success,
        status_code=(
            response_metadata.get("status_code")
            if response_metadata is not None
            else None
        ),
        content_type=(
            response_metadata.get("content_type")
            if response_metadata is not None
            else None
        ),
        content_bytes=_raw_content_bytes(items),
        latency_ms=round(max(0.0, latency_ms)),
        error_type=first_error.error_type if first_error else None,
        error_message=first_error.error_message if first_error else None,
        skipped=skipped,
        skip_reason=skip_reason,
        metadata=metadata,
    )


def skipped_source_fetch_result(
    source: SourceDefinition,
    *,
    request_id: str,
    skip_reason: str,
    metadata: dict[str, Any],
) -> SourceFetchResult:
    result = source_fetch_result(
        source,
        request_id=request_id,
        success=False,
        latency_ms=0,
        items=[],
        errors=[],
        skipped=True,
        skip_reason=skip_reason,
    )
    result_metadata = dict(result.metadata)
    result_metadata["skip"] = {
        key: value for key, value in metadata.items() if value is not None
    }
    return replace(result, metadata=result_metadata)


def with_error_request_id(errors: list[SourceError], request_id: str) -> list[SourceError]:
    linked_errors = []
    for error in errors:
        metadata = dict(error.metadata)
        metadata.setdefault("request_id", request_id)
        linked_errors.append(replace(error, metadata=metadata))
    return linked_errors


def error_metadata_bool(error: SourceError, key: str, *, default: bool) -> bool:
    if key == "retryable" and error.retryable is not None:
        return error.retryable
    value = error.metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def error_phase(error: SourceError) -> str | None:
    value = error.metadata.get("phase")
    return str(value) if value is not None else None


def _fetch_policy_metadata(fetch_policy: SourceFetchPolicy) -> dict[str, Any]:
    return {
        "fetch_timeout_seconds": fetch_policy.timeout_seconds,
        "fetch_max_bytes": fetch_policy.max_bytes,
        "max_redirects": fetch_policy.max_redirects,
        "robots_policy": fetch_policy.respect_robots,
        "rate_limit_per_domain_per_minute": fetch_policy.rate_limit_per_domain_per_minute,
        "retry_times": fetch_policy.retry_times,
        "retry_on_status_codes": list(fetch_policy.retry_on_status_codes),
    }


def _raw_content_bytes(items: list[Any]) -> int | None:
    total = 0
    found = False
    for item in items:
        raw_content = getattr(item, "raw_content", None)
        if raw_content is None:
            continue
        found = True
        total += len(str(raw_content).encode("utf-8"))
    return total if found else None
