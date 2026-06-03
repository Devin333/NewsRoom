from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel
from business.foundation.models.source import (
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
    SourceFetchRequest,
    SourceFetchResult,
    SourceReliability,
    SourceType,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_names import source_connector_name


FETCH_RESPONSE_METADATA_KEY = "fetch_response"


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def dt(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def source_fetch_request_id(existing: list[SourceFetchRequest], source: SourceDefinition) -> str:
    return f"source-fetch-{len(existing) + 1:04d}-{source.source_id}"


class SourceFetchResultMetadata(PrimitiveModel):
    schema_version: str = "business.cross_board.daily_source_fetch.metadata.v1"
    source_type: str
    url: str | None = None
    item_count: int = 0
    error_count: int = 0
    response_url: str | None = None
    response_headers: dict[str, Any] = Field(default_factory=dict)
    fetch_response: dict[str, Any] | None = None
    skip: dict[str, Any] | None = None

    @classmethod
    def from_observations(
        cls,
        *,
        source: SourceDefinition,
        items: list[Any],
        errors: list[SourceError],
    ) -> "SourceFetchResultMetadata":
        response_metadata = response_metadata_from_observations(items=items, errors=errors)
        return cls(
            source_type=SourceType(source.source_type).value,
            url=source.url,
            item_count=len(items),
            error_count=len(errors),
            response_url=response_metadata.get("url") if response_metadata is not None else None,
            response_headers=response_metadata.get("headers", {}) if response_metadata is not None else {},
            fetch_response=response_metadata,
        )

    @classmethod
    def from_result_metadata(cls, metadata: dict[str, Any]) -> "SourceFetchResultMetadata":
        formal = metadata.get("source_fetch_result_metadata")
        payload = dict(formal) if isinstance(formal, dict) else {}
        return cls(
            source_type=str(payload.get("source_type") or metadata.get("source_type") or "unknown"),
            url=payload.get("url") or metadata.get("url"),
            item_count=int(_metadata_value(payload, metadata, "item_count", default=0)),
            error_count=int(_metadata_value(payload, metadata, "error_count", default=0)),
            response_url=payload.get("response_url") or metadata.get("response_url"),
            response_headers=dict(payload.get("response_headers") or metadata.get("response_headers") or {}),
            fetch_response=payload.get("fetch_response") or metadata.get("fetch_response"),
            skip=payload.get("skip") or metadata.get("skip"),
        )

    def with_counts(self, *, item_count: int, error_count: int) -> "SourceFetchResultMetadata":
        return self.model_copy(update={"item_count": item_count, "error_count": error_count})

    def with_skip(self, skip: dict[str, Any]) -> "SourceFetchResultMetadata":
        return self.model_copy(update={"skip": dict(skip)})

    def to_result_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source_type": self.source_type,
            "url": self.url,
            "item_count": self.item_count,
            "error_count": self.error_count,
            "source_fetch_result_metadata": self.to_dict(),
        }
        if self.fetch_response is not None:
            metadata["response_url"] = self.response_url
            metadata["response_headers"] = dict(self.response_headers)
            metadata["fetch_response"] = dict(self.fetch_response)
        if self.skip is not None:
            metadata["skip"] = dict(self.skip)
        return metadata


class SourceErrorRuntimeMetadata(PrimitiveModel):
    schema_version: str = "business.cross_board.daily_source_error.runtime_metadata.v1"
    retryable: bool = True
    source_health_affecting: bool = True
    phase: str | None = None
    request_id: str | None = None

    @classmethod
    def from_error(cls, error: SourceError) -> "SourceErrorRuntimeMetadata":
        metadata = dict(error.metadata or {})
        return cls(
            retryable=(
                bool(error.retryable)
                if error.retryable is not None
                else _bool_value(metadata.get("retryable"), default=True)
            ),
            source_health_affecting=_bool_value(
                metadata.get("source_health_affecting"),
                default=True,
            ),
            phase=_optional_text(metadata.get("phase")),
            request_id=_optional_text(metadata.get("request_id")),
        )


def _metadata_value(
    formal: dict[str, Any],
    legacy: dict[str, Any],
    key: str,
    *,
    default: Any,
) -> Any:
    if key in formal:
        return formal[key]
    if key in legacy:
        return legacy[key]
    return default


def response_metadata_from_observations(
    *,
    items: list[Any] | None = None,
    errors: list[Any] | None = None,
) -> dict[str, Any] | None:
    for value in list(items or []) + list(errors or []):
        metadata = _object_metadata(value)
        response_metadata = metadata.get(FETCH_RESPONSE_METADATA_KEY)
        if isinstance(response_metadata, dict):
            return {
                "status_code": _optional_int(response_metadata.get("status_code")),
                "content_type": _optional_text(response_metadata.get("content_type")),
                "url": _optional_text(response_metadata.get("url")),
                "headers": _string_dict(response_metadata.get("headers")),
            }
    return None


def source_fetch_request(
    source: SourceDefinition,
    *,
    request_id: str,
    request: dict[str, Any],
    limit: int,
    profile: str,
    fetch_policy: SourceFetchPolicy | None = None,
    connector_name: str | None = None,
    connector_options: SourceConnectorRuntimeOptions | None = None,
) -> SourceFetchRequest:
    query = None
    source_type = SourceType(source.source_type)
    if source_type == SourceType.ARXIV:
        options = connector_options or SourceConnectorRuntimeOptions.from_source(source, request=request)
        query = options.query or ""
    user_agent = fetch_policy.user_agent if fetch_policy is not None else source.user_agent
    resolved_connector_name = connector_name or source_connector_name(source)
    return SourceFetchRequest(
        request_id=request_id,
        source_id=source.source_id,
        source_type=source_type,
        url=source.url,
        query=query,
        timeout_seconds=fetch_policy.timeout_seconds if fetch_policy is not None else 15.0,
        max_bytes=fetch_policy.max_bytes if fetch_policy is not None else 1_000_000,
        max_redirects=fetch_policy.max_redirects if fetch_policy is not None else 3,
        user_agent=user_agent,
        headers={"User-Agent": user_agent} if user_agent else {},
        limit=limit,
        connector_name=resolved_connector_name,
        metadata={
            "profile": profile,
            "topic": request.get("topic"),
            "source_name": source.name,
            "reliability": SourceReliability(source.reliability).value,
            "authority_score": source.authority_score,
            "fetch_interval_seconds": source.fetch_interval_seconds,
            "respect_robots": source.respect_robots,
            "connector_name": resolved_connector_name,
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
    formal_metadata = SourceFetchResultMetadata.from_result_metadata(metadata).with_counts(
        item_count=len(items),
        error_count=len(errors),
    )
    metadata.update(formal_metadata.to_result_metadata())
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
    metadata_payload = SourceFetchResultMetadata.from_observations(
        source=source,
        items=items,
        errors=errors,
    )
    response_metadata = metadata_payload.fetch_response
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
        metadata=metadata_payload.to_result_metadata(),
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
    skip_metadata = {key: value for key, value in metadata.items() if value is not None}
    result_metadata = SourceFetchResultMetadata.from_result_metadata(result.metadata).with_skip(skip_metadata)
    return replace(result, metadata=result_metadata.to_result_metadata())


def with_error_request_id(errors: list[SourceError], request_id: str) -> list[SourceError]:
    linked_errors = []
    for error in errors:
        metadata = dict(error.metadata)
        metadata.setdefault("request_id", request_id)
        linked_errors.append(replace(error, metadata=metadata))
    return linked_errors


def error_metadata_bool(error: SourceError, key: str, *, default: bool) -> bool:
    runtime_metadata = SourceErrorRuntimeMetadata.from_error(error)
    if key == "retryable" and error.retryable is not None:
        return runtime_metadata.retryable
    if key == "source_health_affecting":
        return runtime_metadata.source_health_affecting
    value = error.metadata.get(key, default)
    return _bool_value(value, default=default)


def error_phase(error: SourceError) -> str | None:
    return SourceErrorRuntimeMetadata.from_error(error).phase


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


def _object_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        metadata = value.get("metadata")
    else:
        metadata = getattr(value, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
