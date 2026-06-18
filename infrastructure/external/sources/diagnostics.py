from __future__ import annotations

from collections.abc import ItemsView
from dataclasses import dataclass, replace
from typing import Any

from infrastructure.external.sources.models import RawSourceItem, SourceError


FETCH_RESPONSE_METADATA_KEY = "fetch_response"


@dataclass(frozen=True)
class SourceFetchResponseMetadata:
    status_code: int | None = None
    content_type: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "content_type": self.content_type,
            "url": self.url,
            "headers": dict(self.headers or {}),
        }


def response_metadata_from_http_response(
    response: Any,
    *,
    url: str | None = None,
) -> SourceFetchResponseMetadata:
    headers = getattr(response, "headers", None)
    response_url = _response_url(response) or url
    content_type = headers.get_content_type() if headers is not None else None
    status_code = _optional_int(getattr(response, "status", None) or getattr(response, "code", None))
    return SourceFetchResponseMetadata(
        status_code=status_code,
        content_type=content_type,
        url=response_url,
        headers=_header_dict(headers),
    )


def attach_response_metadata_to_items(
    items: list[RawSourceItem],
    response_metadata: SourceFetchResponseMetadata | None,
) -> list[RawSourceItem]:
    if response_metadata is None:
        return items
    return [
        replace(item, metadata=_metadata_with_response(item.metadata, response_metadata))
        for item in items
    ]


def attach_response_metadata_to_error(
    error: SourceError,
    response_metadata: SourceFetchResponseMetadata | None,
) -> SourceError:
    if response_metadata is None:
        return error
    return replace(error, metadata=_metadata_with_response(error.metadata, response_metadata))


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


def _metadata_with_response(
    metadata: dict[str, Any],
    response_metadata: SourceFetchResponseMetadata,
) -> dict[str, Any]:
    updated = dict(metadata)
    updated[FETCH_RESPONSE_METADATA_KEY] = response_metadata.to_dict()
    return updated


def _object_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        metadata = value.get("metadata")
    else:
        metadata = getattr(value, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _response_url(response: Any) -> str | None:
    get_url = getattr(response, "geturl", None)
    if callable(get_url):
        value = get_url()
        return str(value) if value else None
    value = getattr(response, "url", None)
    return str(value) if value else None


def _header_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    items = getattr(headers, "items", None)
    if callable(items):
        header_items = items()
        if isinstance(header_items, ItemsView):
            return {str(key): str(value) for key, value in header_items}
        if isinstance(header_items, list):
            return {str(key): str(value) for key, value in header_items}
    return {}


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
