from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from business.foundation.models.source import RawSourceItem, SourceError, SourceFetchRequest, SourceFetchResult
from business.foundation.models.source_error_normalization import normalize_source_errors
from business.layers.signal.source_processing.error_metadata import SOURCE_ERROR_RUNTIME_METADATA_KEY
from framework.shared.json import to_jsonable as _to_json_safe


FETCH_RESPONSE_METADATA_KEY = "fetch_response"
SOURCE_FETCH_RESULT_METADATA_KEY = "source_fetch_result_metadata"


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
            metadata = _SourceFetchResultArtifactMetadataView.from_metadata(value.metadata)
            return cls(
                request_id=value.request_id,
                source_id=value.source_id,
                payload=value,
                status_code=value.status_code,
                content_type=value.content_type,
                response_url=metadata.response_url,
                response_headers=metadata.response_headers,
            )
        if isinstance(value, dict):
            metadata = _SourceFetchResultArtifactMetadataView.from_metadata(_metadata(value))
            return cls(
                request_id=_required_text(value.get("request_id"), "source fetch result request_id"),
                source_id=_required_text(value.get("source_id"), "source fetch result source_id"),
                payload=value,
                status_code=_optional_int(value.get("status_code")),
                content_type=_optional_text(value.get("content_type")),
                response_url=metadata.response_url,
                response_headers=metadata.response_headers,
            )
        raise TypeError("source fetch result artifacts must be SourceFetchResult or mapping values")


@dataclass(frozen=True)
class SourceErrorArtifactInput:
    source_id: str
    error_id: str
    payload: SourceError
    request_id: str | None = None
    request_ref: Any = None
    response_ref: Any = None

    @classmethod
    def from_error(cls, value: SourceError, *, index: int) -> "SourceErrorArtifactInput":
        metadata = _SourceErrorArtifactMetadataView.from_metadata(value.metadata)
        return cls(
            source_id=value.source_id,
            error_id=_source_error_id(value, index),
            payload=value,
            request_id=metadata.request_id,
            request_ref=value.request_ref,
            response_ref=value.response_ref,
        )


def source_error_artifact_inputs(values: Any) -> list[SourceErrorArtifactInput]:
    return [
        SourceErrorArtifactInput.from_error(source_error, index=index)
        for index, source_error in enumerate(
            normalize_source_errors(
                _sequence_values(values, context="source artifact errors"),
                context="source artifact errors",
            ),
            start=1,
        )
    ]


def source_fetch_result_artifact_inputs(values: Any) -> list[SourceFetchResultArtifactInput]:
    return [
        SourceFetchResultArtifactInput.from_value(value)
        for value in _sequence_values(values, context="source fetch result artifacts")
    ]


def source_fetch_request_artifact_inputs(values: Any) -> list[SourceFetchRequestArtifactInput]:
    return [
        SourceFetchRequestArtifactInput.from_value(value)
        for value in _sequence_values(values, context="source fetch request artifacts")
    ]


def source_item_artifact_inputs(values: Any) -> list[SourceItemArtifactInput]:
    return [
        SourceItemArtifactInput.from_value(value)
        for value in _sequence_values(values, context="source item artifacts")
    ]


def _sequence_values(values: Any, *, context: str) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, Mapping) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{context} must be a sequence")
    try:
        return list(values)
    except TypeError as exc:
        raise TypeError(f"{context} must be a sequence") from exc


def _metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


@dataclass(frozen=True)
class _SourceFetchResultArtifactMetadataView:
    formal: dict[str, Any]
    legacy: dict[str, Any]

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "_SourceFetchResultArtifactMetadataView":
        legacy = _metadata_dict(metadata)
        return cls(
            formal=_metadata_dict(legacy.get(SOURCE_FETCH_RESULT_METADATA_KEY)),
            legacy=legacy,
        )

    @property
    def response_url(self) -> str | None:
        return _optional_text(self._truthy("response_url"))

    @property
    def response_headers(self) -> dict[str, Any]:
        response_headers = self._truthy("response_headers")
        if isinstance(response_headers, dict):
            return dict(response_headers)
        fetch_response = self._truthy(FETCH_RESPONSE_METADATA_KEY)
        if isinstance(fetch_response, dict) and isinstance(fetch_response.get("headers"), dict):
            return dict(fetch_response["headers"])
        return {}

    def _truthy(self, key: str, default: Any = None) -> Any:
        return self.formal.get(key) or self.legacy.get(key) or default


@dataclass(frozen=True)
class _SourceErrorArtifactMetadataView:
    formal: dict[str, Any]
    legacy: dict[str, Any]

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "_SourceErrorArtifactMetadataView":
        legacy = _metadata_dict(metadata)
        return cls(
            formal=_metadata_dict(legacy.get(SOURCE_ERROR_RUNTIME_METADATA_KEY)),
            legacy=legacy,
        )

    @property
    def request_id(self) -> str | None:
        return _optional_text(self._truthy("request_id"))

    def _truthy(self, key: str, default: Any = None) -> Any:
        return self.formal.get(key) or self.legacy.get(key) or default


def _metadata_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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


def _source_error_id(source_error: SourceError, index: int) -> str:
    digest = _stable_id(source_error)[:12]
    return f"{index:04d}_{source_error.source_id}_{source_error.error_type}_{digest}"


__all__ = [
    "SourceErrorArtifactInput",
    "SourceFetchRequestArtifactInput",
    "SourceFetchResultArtifactInput",
    "SourceItemArtifactInput",
    "source_error_artifact_inputs",
    "source_fetch_request_artifact_inputs",
    "source_fetch_result_artifact_inputs",
    "source_item_artifact_inputs",
]
