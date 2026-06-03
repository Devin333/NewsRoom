from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from business.foundation.models.source import RawSourceItem, SourceFetchRequest, SourceFetchResult
from framework.shared.json import to_jsonable as _to_json_safe


@dataclass(frozen=True)
class SourceItemArtifactInput:
    source_item_id: str
    source_id: str
    payload: Any
    raw_content: Any = None
    raw_artifact_ref: Any = None
    parse_artifact_ref: Any = None

    @classmethod
    def from_value(cls, value: RawSourceItem | dict[str, Any]) -> "SourceItemArtifactInput":
        if isinstance(value, RawSourceItem):
            return cls(
                source_item_id=value.source_item_id,
                source_id=value.source_id,
                payload=value,
                raw_content=value.raw_content,
                raw_artifact_ref=value.raw_artifact_ref,
                parse_artifact_ref=value.parse_artifact_ref,
            )
        if isinstance(value, dict):
            return cls(
                source_item_id=_optional_text(value.get("source_item_id")) or _stable_id(value),
                source_id=_optional_text(value.get("source_id")) or "unknown-source",
                payload=value,
                raw_content=value.get("raw_content"),
                raw_artifact_ref=value.get("raw_artifact_ref"),
                parse_artifact_ref=value.get("parse_artifact_ref"),
            )
        raise TypeError("source item artifacts must be RawSourceItem or mapping values")


@dataclass(frozen=True)
class SourceFetchRequestArtifactInput:
    request_id: str
    source_id: str
    payload: Any

    @classmethod
    def from_value(cls, value: SourceFetchRequest | dict[str, Any]) -> "SourceFetchRequestArtifactInput":
        if isinstance(value, SourceFetchRequest):
            return cls(
                request_id=value.request_id,
                source_id=value.source_id,
                payload=value,
            )
        if isinstance(value, dict):
            return cls(
                request_id=_optional_text(value.get("request_id")) or _stable_id(value),
                source_id=_optional_text(value.get("source_id")) or "unknown-source",
                payload=value,
            )
        raise TypeError("source fetch request artifacts must be SourceFetchRequest or mapping values")


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


def source_fetch_request_artifact_inputs(values: Any) -> list[SourceFetchRequestArtifactInput]:
    return [SourceFetchRequestArtifactInput.from_value(value) for value in list(values or [])]


def source_item_artifact_inputs(values: Any) -> list[SourceItemArtifactInput]:
    return [SourceItemArtifactInput.from_value(value) for value in list(values or [])]


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


def _stable_id(value: Any) -> str:
    payload = repr(_to_json_safe(value)).encode("utf-8", errors="replace")
    return sha256(payload).hexdigest()


__all__ = [
    "SourceFetchRequestArtifactInput",
    "SourceFetchResultArtifactInput",
    "SourceItemArtifactInput",
    "source_fetch_request_artifact_inputs",
    "source_fetch_result_artifact_inputs",
    "source_item_artifact_inputs",
]
