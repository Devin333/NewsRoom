from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.framework.artifacts.filesystem import ArtifactManager
from storage.artifacts import ArtifactRef


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
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
        source_errors: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        entries: list[dict[str, Any]] = []

        for raw_item in raw_items or []:
            source_id = _string_value(raw_item, "source_id", default="unknown-source")
            object_id = _string_value(raw_item, "source_item_id", default=_stable_id(raw_item))
            path = f"sources/items/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_item",
                    "source_id": source_id,
                    "source_item_id": object_id,
                    "item": _redact(_to_json_safe(raw_item)),
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
            entry = {
                "artifact_type": "source_item",
                "artifact_id": artifact_ref.artifact_id,
                "source_id": source_id,
                "object_id": object_id,
                "path": path,
                "size_bytes": artifact_path.stat().st_size,
                "content_type": artifact_ref.content_type,
                "checksum": artifact_ref.checksum,
                "redacted": artifact_ref.redacted,
                "artifact_ref": artifact_ref.to_dict(),
            }
            entry.update(_raw_content_fingerprint(raw_item))
            entries.append(entry)

        for index, source_error in enumerate(source_errors or [], start=1):
            source_id = _string_value(source_error, "source_id", default="unknown-source")
            object_id = _source_error_id(source_error, index)
            path = f"sources/errors/{_path_segment(source_id)}/{_path_segment(object_id)}.json"
            artifact_path = self._artifact_manager.write_json(
                run_id,
                path,
                {
                    "artifact_type": "source_error",
                    "source_id": source_id,
                    "error_id": object_id,
                    "error": _redact(_to_json_safe(source_error)),
                },
            )
            artifact_ref = _artifact_ref(
                run_id=run_id,
                artifact_type="source_error",
                source_id=source_id,
                object_id=object_id,
                path=path,
                artifact_path=artifact_path,
            )
            entries.append(
                {
                    "artifact_type": "source_error",
                    "artifact_id": artifact_ref.artifact_id,
                    "source_id": source_id,
                    "object_id": object_id,
                    "path": path,
                    "size_bytes": artifact_path.stat().st_size,
                    "content_type": artifact_ref.content_type,
                    "checksum": artifact_ref.checksum,
                    "redacted": artifact_ref.redacted,
                    "artifact_ref": artifact_ref.to_dict(),
                }
            )

        if not entries:
            return None

        source_artifacts = {
            "entries": entries,
            "item_count": sum(1 for entry in entries if entry["artifact_type"] == "source_item"),
            "error_count": sum(1 for entry in entries if entry["artifact_type"] == "source_error"),
        }
        self._artifact_manager.write_json(run_id, "source_artifacts/index.json", source_artifacts)
        return source_artifacts


def _source_error_id(source_error: Any, index: int) -> str:
    source_id = _string_value(source_error, "source_id", default="unknown-source")
    error_type = _string_value(source_error, "error_type", default="source_error")
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
) -> ArtifactRef:
    data = artifact_path.read_bytes()
    return ArtifactRef(
        artifact_id=_artifact_id(artifact_type, source_id, object_id),
        run_id=run_id,
        artifact_type=artifact_type,
        path=path,
        content_type="application/json",
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
    if isinstance(raw_item, dict):
        raw_content = raw_item.get("raw_content")
    else:
        raw_content = getattr(raw_item, "raw_content", None)
    if raw_content is None:
        return {}
    raw_bytes = str(raw_content).encode("utf-8")
    return {
        "raw_content_bytes": len(raw_bytes),
        "raw_content_sha256": sha256(raw_bytes).hexdigest(),
    }


def _path_segment(value: str) -> str:
    segment = _SAFE_SEGMENT_RE.sub("_", value.strip())
    return segment.strip("._") or "unknown"


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _to_json_safe(value.to_dict())
    if is_dataclass(value):
        return _to_json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    return value


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
    redacted = _SECRET_RE.sub("[REDACTED]", redacted)
    return _redact_url(redacted)


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc or not parsed.query:
        return value
    query = []
    changed = False
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            query.append((key, "[REDACTED]"))
            changed = True
        else:
            query.append((key, item))
    if not changed:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
