from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.foundation.models.source import SourceFetchResult


@dataclass(frozen=True)
class SourceFetchResultArtifactInput:
    request_id: str
    source_id: str
    payload: Any
    status_code: int | None = None
    content_type: str | None = None
    response_url: str | None = None
    response_headers: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: SourceFetchResult | dict[str, Any]) -> "SourceFetchResultArtifactInput":
        if isinstance(value, SourceFetchResult):
            return cls(
                request_id=value.request_id,
                source_id=value.source_id,
                payload=value,
                status_code=value.status_code,
                content_type=value.content_type,
                response_url=_optional_text(value.metadata.get("response_url")),
                response_headers=_response_headers_from_metadata(value.metadata),
            )
        if isinstance(value, dict):
            return cls(
                request_id=_required_text(value.get("request_id"), "source fetch result request_id"),
                source_id=_required_text(value.get("source_id"), "source fetch result source_id"),
                payload=value,
                status_code=_optional_int(value.get("status_code")),
                content_type=_optional_text(value.get("content_type")),
                response_url=_optional_text(_metadata(value).get("response_url")),
                response_headers=_response_headers_from_metadata(_metadata(value)),
            )
        raise TypeError("source fetch result artifacts must be SourceFetchResult or mapping values")


def source_fetch_result_artifact_inputs(values: Any) -> list[SourceFetchResultArtifactInput]:
    return [SourceFetchResultArtifactInput.from_value(value) for value in list(values or [])]


def _metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _response_headers_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    response_headers = metadata.get("response_headers")
    if isinstance(response_headers, dict):
        return dict(response_headers)
    fetch_response = metadata.get("fetch_response")
    if isinstance(fetch_response, dict) and isinstance(fetch_response.get("headers"), dict):
        return dict(fetch_response["headers"])
    return {}


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise TypeError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


__all__ = ["SourceFetchResultArtifactInput", "source_fetch_result_artifact_inputs"]
