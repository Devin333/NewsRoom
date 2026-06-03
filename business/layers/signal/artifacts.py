from __future__ import annotations

import re
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from framework.shared.json import to_jsonable as _to_json_safe
from business.foundation.models.source import SourceError
from business.foundation.models.source_error_normalization import normalize_source_errors
from business.layers.signal.artifact_refs import SignalArtifactRef
from business.layers.signal.source_artifact_inputs import (
    SourceFetchResultArtifactInput,
    source_fetch_result_artifact_inputs,
)
from framework.artifacts import ArtifactManager


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_BASIC_RE = re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=_-]+")
_SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{8,})")
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "signature",
)


class SourceArtifactWriter:
    def __init__(self, artifact_manager: ArtifactManager) -> None:
        self._artifact_manager = artifact_manager

    def write_source_artifacts(
        self,
        run_id: str,
        *,
        raw_items: list[Any] | None = None,
        source_fetch_requests: list[Any] | None = None,
        source_fetch_results: list[Any] | None = None,
        source_errors: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        entries: list[dict[str, Any]] = []
        request_refs_by_request_id: dict[str, SignalArtifactRef] = {}
        request_refs_by_source_id: dict[str, list[SignalArtifactRef]] = {}
        response_refs_by_request_id: dict[str, SignalArtifactRef] = {}
        response_refs_by_source_id: dict[str, list[SignalArtifactRef]] = {}
        parsed_items_by_source: dict[str, list[dict[str, Any]]] = {}

        for raw_item in raw_items or []:
            source_id = _string_value(raw_item, "source_id", default="unknown-source")
            object_id = _string_value(raw_item, "source_item_id", default=_stable_id(raw_item))
            raw_content_entry, raw_content_ref = self._write_raw_content_artifact(
                run_id,
                raw_item=raw_item,
                source_id=source_id,
                object_id=object_id,
            )
            existing_raw_ref = _existing_artifact_ref(raw_item, "raw_artifact_ref")
            raw_ref = raw_content_ref or existing_raw_ref
            existing_parse_ref = _existing_artifact_ref(raw_item, "parse_artifact_ref")
            path = f"sources/items/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            parse_ref_payload = existing_parse_ref or _planned_artifact_ref(
                run_id=run_id,
                artifact_type="source_item",
                source_id=source_id,
                object_id=object_id,
                path=path,
                content_type="application/json",
            )
            item_payload = _source_item_payload(
                raw_item,
                source_id=source_id,
                object_id=object_id,
                raw_artifact_ref=raw_ref,
                parse_artifact_ref=parse_ref_payload,
            )
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_item",
                    "source_id": source_id,
                    "source_item_id": object_id,
                    "item": item_payload,
                    "raw_artifact_ref": _to_json_safe(raw_ref) if raw_ref is not None else None,
                    "parse_artifact_ref": _to_json_safe(parse_ref_payload),
                },
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_item",
                source_id=source_id,
                object_id=object_id,
                path=path,
                artifact_path=artifact_path,
            )
            entry = _entry_from_ref(
                artifact_ref=artifact_ref,
                source_id=source_id,
                object_id=object_id,
                artifact_path=artifact_path,
            )
            if raw_ref is not None:
                entry["raw_artifact_ref"] = _to_json_safe(raw_ref)
            entry["parse_artifact_ref"] = artifact_ref.to_dict()
            entry.update(_raw_content_fingerprint(raw_item))
            entries.append(entry)
            parsed_items_by_source.setdefault(source_id, []).append(
                _parsed_item_entry(
                    item_payload,
                    item_artifact_ref=artifact_ref,
                    raw_artifact_ref=raw_ref,
                )
            )
            if raw_content_entry is not None:
                entries.append(raw_content_entry)

        for source_id, parsed_items in sorted(parsed_items_by_source.items()):
            path = f"sources/{_path_segment(source_id)}/parsed_items.json"
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_parsed_items",
                    "source_id": source_id,
                    "item_count": len(parsed_items),
                    "items": parsed_items,
                },
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_parsed_items",
                source_id=source_id,
                object_id="parsed_items",
                path=path,
                artifact_path=artifact_path,
            )
            entry = _entry_from_ref(
                artifact_ref=artifact_ref,
                source_id=source_id,
                object_id="parsed_items",
                artifact_path=artifact_path,
            )
            entry["item_count"] = len(parsed_items)
            entry["item_artifact_refs"] = [
                parsed_item["item_artifact_ref"] for parsed_item in parsed_items
            ]
            entries.append(entry)

        for fetch_request in source_fetch_requests or []:
            source_id = _string_value(fetch_request, "source_id", default="unknown-source")
            object_id = _string_value(fetch_request, "request_id", default=_stable_id(fetch_request))
            path = f"sources/fetch_requests/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_fetch_request",
                    "source_id": source_id,
                    "request_id": object_id,
                    "fetch_request": _redact(_to_json_safe(fetch_request)),
                },
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_fetch_request",
                source_id=source_id,
                object_id=object_id,
                path=path,
                artifact_path=artifact_path,
            )
            _remember_ref(
                request_refs_by_request_id,
                request_refs_by_source_id,
                artifact_ref=artifact_ref,
                source_id=source_id,
                request_id=object_id,
            )
            entries.append(
                _entry_from_ref(
                    artifact_ref=artifact_ref,
                    source_id=source_id,
                    object_id=object_id,
                    artifact_path=artifact_path,
                )
            )

        for fetch_result in source_fetch_result_artifact_inputs(source_fetch_results):
            source_id = fetch_result.source_id
            object_id = fetch_result.request_id
            response_headers_entry, response_headers_ref = self._write_response_headers_artifact(
                run_id,
                fetch_result=fetch_result,
                source_id=source_id,
                object_id=object_id,
            )
            path = f"sources/fetch_results/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            fetch_result_payload = _redact(_to_json_safe(fetch_result.payload))
            response_headers_ref_payload = _ref_payload(response_headers_ref)
            if isinstance(fetch_result_payload, dict) and response_headers_ref_payload is not None:
                fetch_result_payload["response_headers_ref"] = response_headers_ref_payload
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_fetch_result",
                    "source_id": source_id,
                    "request_id": object_id,
                    "fetch_result": fetch_result_payload,
                    "response_headers_ref": response_headers_ref_payload,
                },
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_fetch_result",
                source_id=source_id,
                object_id=object_id,
                path=path,
                artifact_path=artifact_path,
            )
            _remember_ref(
                response_refs_by_request_id,
                response_refs_by_source_id,
                artifact_ref=artifact_ref,
                source_id=source_id,
                request_id=object_id,
            )
            entries.append(
                _entry_from_ref(
                    artifact_ref=artifact_ref,
                    source_id=source_id,
                    object_id=object_id,
                    artifact_path=artifact_path,
                )
            )
            if response_headers_entry is not None:
                entries.append(response_headers_entry)

        for index, source_error in enumerate(
            normalize_source_errors(source_errors, context="source artifact errors"),
            start=1,
        ):
            source_id = source_error.source_id
            object_id = _source_error_id(source_error, index)
            path = f"sources/errors/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            request_id = _optional_string(source_error.metadata.get("request_id"))
            request_ref = _resolve_error_ref(
                source_error,
                "request_ref",
                request_id=request_id,
                source_id=source_id,
                refs_by_request_id=request_refs_by_request_id,
                refs_by_source_id=request_refs_by_source_id,
            )
            response_ref = _resolve_error_ref(
                source_error,
                "response_ref",
                request_id=request_id,
                source_id=source_id,
                refs_by_request_id=response_refs_by_request_id,
                refs_by_source_id=response_refs_by_source_id,
            )
            error_payload = _redact(_to_json_safe(source_error))
            request_ref_payload = _ref_payload(request_ref)
            response_ref_payload = _ref_payload(response_ref)
            if isinstance(error_payload, dict):
                if request_ref_payload is not None:
                    error_payload["request_ref"] = request_ref_payload
                if response_ref_payload is not None:
                    error_payload["response_ref"] = response_ref_payload
            payload = {
                "artifact_type": "source_error",
                "source_id": source_id,
                "error_id": object_id,
                "error": error_payload,
            }
            if request_ref_payload is not None:
                payload["request_ref"] = request_ref_payload
            if response_ref_payload is not None:
                payload["response_ref"] = response_ref_payload
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                payload,
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_error",
                source_id=source_id,
                object_id=object_id,
                path=path,
                artifact_path=artifact_path,
            )
            entry = _entry_from_ref(
                artifact_ref=artifact_ref,
                source_id=source_id,
                object_id=object_id,
                artifact_path=artifact_path,
            )
            if request_id is not None:
                entry["request_id"] = request_id
            if request_ref_payload is not None:
                entry["request_ref"] = request_ref_payload
            if response_ref_payload is not None:
                entry["response_ref"] = response_ref_payload
            entries.append(entry)

        if not entries:
            return None

        source_artifacts = {
            "entries": entries,
            "item_count": sum(1 for entry in entries if entry["artifact_type"] == "source_item"),
            "error_count": sum(1 for entry in entries if entry["artifact_type"] == "source_error"),
            "raw_content_count": sum(
                1 for entry in entries if entry["artifact_type"] == "source_raw_content"
            ),
            "fetch_request_count": sum(
                1 for entry in entries if entry["artifact_type"] == "source_fetch_request"
            ),
            "fetch_result_count": sum(
                1 for entry in entries if entry["artifact_type"] == "source_fetch_result"
            ),
            "parsed_items_count": sum(
                1 for entry in entries if entry["artifact_type"] == "source_parsed_items"
            ),
            "response_headers_count": sum(
                1 for entry in entries if entry["artifact_type"] == "source_response_headers"
            ),
        }
        self._artifact_manager.write_json(run_id, "source_artifacts/index.json", source_artifacts)
        return source_artifacts

    def _write_raw_content_artifact(
        self,
        run_id: str,
        *,
        raw_item: Any,
        source_id: str,
        object_id: str,
    ) -> tuple[dict[str, Any] | None, SignalArtifactRef | None]:
        raw_content = _raw_content(raw_item)
        if raw_content is None:
            return None, None
        path = f"sources/{_path_segment(source_id)}/{_path_segment(object_id)}/raw_content.bin"
        redacted_content = _redact_string(str(raw_content)).encode("utf-8")
        artifact_path = self._artifact_manager.write_bytes(
            run_id,
            path,
            redacted_content,
        )
        artifact_ref = _artifact_ref(
            run_id=run_id,
            artifact_type="source_raw_content",
            source_id=source_id,
            object_id=object_id,
            path=path,
            artifact_path=artifact_path,
            content_type="application/octet-stream",
        )
        entry = _entry_from_ref(
            artifact_ref=artifact_ref,
            source_id=source_id,
            object_id=object_id,
            artifact_path=artifact_path,
        )
        entry.update(_raw_content_fingerprint(raw_item))
        return entry, artifact_ref

    def _write_response_headers_artifact(
        self,
        run_id: str,
        *,
        fetch_result: SourceFetchResultArtifactInput,
        source_id: str,
        object_id: str,
    ) -> tuple[dict[str, Any] | None, SignalArtifactRef | None]:
        response_headers = fetch_result.response_headers
        if not response_headers:
            return None, None
        path = f"sources/response_headers/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
        artifact_path = self._artifact_manager.write_json(
            run_id,
            path,
            {
                "artifact_type": "source_response_headers",
                "source_id": source_id,
                "request_id": object_id,
                "status_code": fetch_result.status_code,
                "content_type": fetch_result.content_type,
                "response_url": _redact(fetch_result.response_url),
                "headers": _redact(response_headers),
            },
        )
        artifact_ref = _artifact_ref(
            run_id=run_id,
            artifact_type="source_response_headers",
            source_id=source_id,
            object_id=object_id,
            path=path,
            artifact_path=artifact_path,
        )
        entry = _entry_from_ref(
            artifact_ref=artifact_ref,
            source_id=source_id,
            object_id=object_id,
            artifact_path=artifact_path,
        )
        entry["status_code"] = fetch_result.status_code
        entry["content_type"] = fetch_result.content_type
        return entry, artifact_ref


def _source_error_id(source_error: SourceError, index: int) -> str:
    source_id = source_error.source_id
    error_type = source_error.error_type
    digest = _stable_id(source_error)[:12]
    return f"{index:04d}_{source_id}_{error_type}_{digest}"


def _artifact_ref(
    *,
    run_id: str,
    artifact_type: str,
    source_id: str,
    object_id: str,
    path: str,
    artifact_path: Any,
    content_type: str = "application/json",
) -> SignalArtifactRef:
    data = artifact_path.read_bytes()
    return SignalArtifactRef(
        artifact_id=_artifact_id(artifact_type, source_id, object_id),
        run_id=run_id,
        artifact_type=artifact_type,
        path=path,
        content_type=content_type,
        size_bytes=len(data),
        checksum=sha256(data).hexdigest(),
        redacted=True,
        metadata={
            "source_id": source_id,
            "object_id": object_id,
            "source_artifact_type": artifact_type,
        },
    )


def _artifact_id(artifact_type: str, source_id: str, object_id: str) -> str:
    prefix = artifact_type.replace("_", "-")
    return f"{prefix}-{_path_segment(source_id)}-{_path_segment(object_id)}"


def _source_item_payload(
    raw_item: Any,
    *,
    source_id: str,
    object_id: str,
    raw_artifact_ref: Any,
    parse_artifact_ref: Any,
) -> Any:
    payload = _redact(_to_json_safe(raw_item))
    if not isinstance(payload, dict):
        return payload
    raw_ref_payload = _to_json_safe(raw_artifact_ref) if raw_artifact_ref is not None else None
    parse_ref_payload = _to_json_safe(parse_artifact_ref)
    if raw_ref_payload is not None:
        payload["raw_artifact_ref"] = raw_ref_payload
    payload["parse_artifact_ref"] = parse_ref_payload
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        lineage = {}
        payload["lineage"] = lineage
    lineage.setdefault("source_id", source_id)
    lineage.setdefault("source_item_id", object_id)
    raw_url = payload.get("url")
    if raw_url is not None:
        lineage.setdefault("raw_url", raw_url)
    if raw_ref_payload is not None:
        lineage["raw_artifact_ref"] = raw_ref_payload
    lineage["parse_artifact_ref"] = parse_ref_payload
    return payload


def _parsed_item_entry(
    item_payload: Any,
    *,
    item_artifact_ref: SignalArtifactRef,
    raw_artifact_ref: Any,
) -> dict[str, Any]:
    summary = _parsed_item_summary(item_payload)
    item_ref_payload = item_artifact_ref.to_dict()
    raw_ref_payload = _to_json_safe(raw_artifact_ref) if raw_artifact_ref is not None else None
    summary["parse_artifact_ref"] = item_ref_payload
    if raw_ref_payload is not None:
        summary["raw_artifact_ref"] = raw_ref_payload
    lineage = summary.get("lineage")
    if isinstance(lineage, dict):
        lineage["parse_artifact_ref"] = item_ref_payload
        if raw_ref_payload is not None:
            lineage["raw_artifact_ref"] = raw_ref_payload
    return {
        "source_item_id": str(
            summary.get("source_item_id")
            or item_artifact_ref.metadata.get("object_id")
            or item_artifact_ref.artifact_id
        ),
        "item_artifact_ref": item_ref_payload,
        "raw_artifact_ref": raw_ref_payload,
        "item": summary,
    }


def _parsed_item_summary(item_payload: Any) -> dict[str, Any]:
    if not isinstance(item_payload, dict):
        return {"value": _redact(_to_json_safe(item_payload))}
    summary_keys = [
        "source_item_id",
        "source_id",
        "source_name",
        "source_type",
        "title",
        "url",
        "fetched_at",
        "published_at",
        "summary",
        "authors",
        "tags",
        "language",
        "raw_artifact_ref",
        "parse_artifact_ref",
        "lineage",
        "metadata",
    ]
    return {
        key: _redact(_to_json_safe(item_payload[key]))
        for key in summary_keys
        if key in item_payload and item_payload[key] is not None
    }


def _planned_artifact_ref(
    *,
    run_id: str,
    artifact_type: str,
    source_id: str,
    object_id: str,
    path: str,
    content_type: str,
) -> dict[str, str]:
    return {
        "artifact_id": _artifact_id(artifact_type, source_id, object_id),
        "run_id": run_id,
        "artifact_type": artifact_type,
        "path": path,
        "content_type": content_type,
    }


def _entry_from_ref(
    *,
    artifact_ref: SignalArtifactRef,
    source_id: str,
    object_id: str,
    artifact_path: Any,
) -> dict[str, Any]:
    return {
        "artifact_type": artifact_ref.artifact_type,
        "artifact_id": artifact_ref.artifact_id,
        "source_id": source_id,
        "object_id": object_id,
        "path": artifact_ref.path,
        "size_bytes": artifact_path.stat().st_size,
        "content_type": artifact_ref.content_type,
        "checksum": artifact_ref.checksum,
        "redacted": artifact_ref.redacted,
        "artifact_ref": artifact_ref.to_dict(),
    }


def _remember_ref(
    refs_by_request_id: dict[str, SignalArtifactRef],
    refs_by_source_id: dict[str, list[SignalArtifactRef]],
    *,
    artifact_ref: SignalArtifactRef,
    source_id: str,
    request_id: str,
) -> None:
    refs_by_request_id[request_id] = artifact_ref
    refs_by_source_id.setdefault(source_id, []).append(artifact_ref)


def _resolve_error_ref(
    source_error: SourceError,
    field_name: str,
    *,
    request_id: str | None,
    source_id: str,
    refs_by_request_id: dict[str, SignalArtifactRef],
    refs_by_source_id: dict[str, list[SignalArtifactRef]],
) -> Any:
    existing_ref = getattr(source_error, field_name)
    if existing_ref is not None:
        return existing_ref
    if request_id:
        request_ref = refs_by_request_id.get(request_id)
        if request_ref is not None:
            return request_ref
    source_refs = refs_by_source_id.get(source_id, [])
    if len(source_refs) == 1:
        return source_refs[0]
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ref_payload(value: Any) -> Any:
    if value is None:
        return None
    return _redact(_to_json_safe(value))


def _stable_id(value: Any) -> str:
    payload = repr(_to_json_safe(value)).encode("utf-8", errors="replace")
    return sha256(payload).hexdigest()


def _string_value(value: Any, name: str, *, default: str) -> str:
    if isinstance(value, dict):
        candidate = value.get(name)
    else:
        candidate = getattr(value, name, None)
    if candidate is None or str(candidate) == "":
        return default
    return str(candidate)


def _raw_content_fingerprint(raw_item: Any) -> dict[str, Any]:
    raw_content = _raw_content(raw_item)
    if raw_content is None:
        return {}
    raw_bytes = str(raw_content).encode("utf-8")
    return {
        "raw_content_bytes": len(raw_bytes),
        "raw_content_sha256": sha256(raw_bytes).hexdigest(),
    }


def _raw_content(raw_item: Any) -> Any:
    if isinstance(raw_item, dict):
        return raw_item.get("raw_content")
    return getattr(raw_item, "raw_content", None)


def _existing_artifact_ref(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _path_segment(value: str) -> str:
    segment = _SAFE_SEGMENT_RE.sub("_", value.strip())
    return segment.strip("._") or "unknown"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", value)
    redacted = _BASIC_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_RE.sub("[REDACTED]", redacted)
    return _redact_url(redacted)


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    netloc = _redacted_netloc(parsed)
    query = []
    changed = False
    if parsed.query:
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            if _is_sensitive_key(key):
                query.append((key, "[REDACTED]"))
                changed = True
            else:
                query.append((key, item))
    if netloc != parsed.netloc:
        changed = True
    if not changed:
        return value
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment))


def _redacted_netloc(parsed: Any) -> str:
    if parsed.username is None and parsed.password is None and "@" not in parsed.netloc:
        return parsed.netloc
    host = parsed.hostname or parsed.netloc.rsplit("@", 1)[-1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"[REDACTED]@{host}{port}"
