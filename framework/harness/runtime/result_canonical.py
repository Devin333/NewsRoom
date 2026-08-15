from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, TypeVar

from framework.events.canonical import (
    EventCanonicalizationError,
    canonical_json_bytes,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.graph.canonical import freeze_json, thaw_json
from framework.shared.time import ensure_utc, format_datetime


_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,511}\Z")
_REFERENCE = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s]{1,2040}\Z|"
    r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,2047}\Z"
)
_EXACT_REFERENCE = re.compile(
    r"(?P<identifier>[A-Za-z0-9][A-Za-z0-9._:/+-]*)@"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9._+-]*)\Z"
)
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})
_RESERVED_CANDIDATE_FIELDS = frozenset(
    {
        "attempt_id",
        "authorization",
        "cache_refs",
        "context_policy",
        "gate_decision",
        "graph_id",
        "graph_version",
        "materialized_refs",
        "memory_write",
        "node_id",
        "parent_checkpoint_ref",
        "persistence_decision",
        "persistence_mode",
        "policy_version",
        "publication",
        "route",
        "routing",
        "run_id",
        "status",
        "tenant_id",
        "tool_authorization",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "hidden_prompt",
        "password",
        "passwd",
        "private_context",
        "raw_prompt",
        "refresh_token",
        "secret",
        "system_prompt",
        "access_token",
    }
)
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_credential",
    "_credentials",
    "_password",
    "_secret",
)

T = TypeVar("T")


def required_text(value: Any, field: str, *, max_length: int = 512) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > max_length
    ):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
            limit=max_length,
        )
    return value


def optional_text(
    value: Any,
    field: str,
    *,
    max_length: int = 512,
) -> str | None:
    if value is None:
        return None
    return required_text(value, field, max_length=max_length)


def identifier(value: Any, field: str) -> str:
    text = required_text(value, field)
    if _IDENTIFIER.fullmatch(text) is None:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return text


def reference(value: Any, field: str) -> str:
    text = required_text(value, field, max_length=2048)
    if _REFERENCE.fullmatch(text) is None:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return text


def exact_reference(value: Any, field: str) -> str:
    text = required_text(value, field)
    match = _EXACT_REFERENCE.fullmatch(text)
    if match is None or match.group("version").casefold() in _MOVING_VERSIONS:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return text


def checksum(value: Any, field: str) -> str:
    text = required_text(value, field)
    if _CHECKSUM.fullmatch(text) is None:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return text


def media_type(value: Any, field: str = "media_type") -> str:
    text = required_text(value, field, max_length=255).casefold()
    if _MEDIA_TYPE.fullmatch(text) is None:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return text


def non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return value


def bounded_int(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    normalized = non_negative_int(value, field)
    if not minimum <= normalized <= maximum:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
            limit=maximum,
            actual=normalized,
        )
    return normalized


def boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return value


def enum_value(enum_type: type[T], value: Any, field: str) -> T:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        ) from exc


def aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return ensure_utc(value)


def datetime_from_json(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        ) from exc
    return aware_datetime(parsed, field)


def datetime_to_json(value: datetime) -> str:
    rendered = format_datetime(aware_datetime(value, "datetime"))
    if rendered is None:
        raise AssertionError("aware datetime unexpectedly rendered as null")
    return rendered


def exact_keys(
    payload: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    model: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or any(
        not isinstance(key, str) for key in payload
    ):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            model=model,
        )
    keys = frozenset(payload)
    if keys - required - optional or required - keys:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            model=model,
        )
    return dict(payload)


def stable_tuple(
    values: Sequence[Any],
    field: str,
    *,
    normalize,
    allow_empty: bool = True,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    normalized = tuple(normalize(value, field) for value in values)
    if (not allow_empty and not normalized) or len(set(normalized)) != len(normalized):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return tuple(sorted(normalized))


def canonical_mapping(
    value: Any,
    field: str,
    *,
    max_depth: int,
    max_keys: int,
    max_bytes: int | None = None,
    allowed_root_fields: frozenset[str] | None = None,
    reject_reserved_root_fields: bool = False,
    reject_sensitive_fields: bool = True,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    if any(not isinstance(key, str) for key in value):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    root_keys = frozenset(value)
    if allowed_root_fields is not None and not root_keys <= allowed_root_fields:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    if reject_reserved_root_fields and root_keys & _RESERVED_CANDIDATE_FIELDS:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    if reject_sensitive_fields:
        _reject_sensitive_keys(value)
    depth, key_count = _shape(value)
    if depth > max_depth or key_count > max_keys:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
            max_depth=max_depth,
            max_keys=max_keys,
        )
    try:
        frozen = freeze_json(value, field)
    except (EventCanonicalizationError, TypeError, ValueError) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        ) from exc
    if not isinstance(frozen, Mapping):
        raise AssertionError("canonical mapping did not remain a mapping")
    if max_bytes is not None and len(canonical_json_bytes(frozen)) > max_bytes:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_TOO_LARGE,
            field=field,
            limit=max_bytes,
        )
    return frozen


def thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    thawed = thaw_json(value)
    if not isinstance(thawed, dict):
        raise AssertionError("canonical mapping did not thaw to dict")
    return thawed


def serialize_candidate(value: Any, content_type: str) -> tuple[Any, bytes]:
    normalized_media_type = media_type(content_type)
    if normalized_media_type == "application/json" or normalized_media_type.endswith("+json"):
        if isinstance(value, Mapping):
            _reject_sensitive_keys(value)
            if frozenset(value) & _RESERVED_CANDIDATE_FIELDS:
                raise result_error(
                    GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                    field="candidate",
                )
        try:
            frozen = freeze_json(value, "candidate")
            return frozen, canonical_json_bytes(frozen)
        except GraphArtifactResultError:
            raise
        except (EventCanonicalizationError, TypeError, ValueError) as exc:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="candidate",
            ) from exc
    if normalized_media_type.startswith("text/"):
        text = required_text(value, "candidate", max_length=536_870_912)
        return text, text.encode("utf-8")
    if not isinstance(value, (bytes, bytearray)):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="candidate",
        )
    detached = bytes(value)
    return detached, detached


def sha256_checksum(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def estimated_tokens(byte_size: int) -> int:
    size = non_negative_int(byte_size, "byte_size")
    return 0 if size == 0 else (size + 3) // 4


def _reject_sensitive_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES):
                raise result_error(
                    GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED,
                    field="candidate",
                )
            _reject_sensitive_keys(item)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            _reject_sensitive_keys(item)


def _shape(value: Any, depth: int = 0) -> tuple[int, int]:
    if isinstance(value, Mapping):
        maximum = depth + 1
        keys = len(value)
        for item in value.values():
            child_depth, child_keys = _shape(item, depth + 1)
            maximum = max(maximum, child_depth)
            keys += child_keys
        return maximum, keys
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        maximum = depth + 1
        keys = 0
        for item in value:
            child_depth, child_keys = _shape(item, depth + 1)
            maximum = max(maximum, child_depth)
            keys += child_keys
        return maximum, keys
    return depth, 0


__all__ = [
    "aware_datetime",
    "boolean",
    "bounded_int",
    "canonical_mapping",
    "checksum",
    "datetime_from_json",
    "datetime_to_json",
    "enum_value",
    "estimated_tokens",
    "exact_keys",
    "exact_reference",
    "identifier",
    "media_type",
    "non_negative_int",
    "optional_text",
    "reference",
    "required_text",
    "serialize_candidate",
    "sha256_checksum",
    "stable_tuple",
    "thaw_mapping",
]
