from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


def required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(f"{field} must be a non-empty string")
    return value.strip()


def optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field=field)


def text_tuple(
    value: Any,
    *,
    field: str,
    required: bool = False,
    unique: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HarnessValidationError(f"{field} must be a list of strings")
    result = tuple(required_text(item, field=field) for item in value)
    if required and not result:
        raise HarnessValidationError(f"{field} must not be empty")
    if unique and len(set(result)) != len(result):
        raise HarnessValidationError(f"{field} must not contain duplicates")
    return result


def frozen_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field} must be an object")
    return MappingProxyType(
        {key: _deep_freeze(item) for key, item in value.items()}
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return deepcopy(value)


def mapping_tuple(value: Any, *, field: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise HarnessValidationError(f"{field} must be a list of objects")
    return tuple(deepcopy(to_jsonable(dict(item))) for item in value)


def strict_payload(value: Any, *, model: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{model} payload must be an object")
    return dict(value)


def reject_fields(payload: Mapping[str, Any], *, model: str) -> None:
    if payload:
        raise HarnessValidationError(
            f"{model} payload contains unsupported fields: "
            + ", ".join(sorted(str(key) for key in payload))
        )


def non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessValidationError(f"{field} must be a non-negative integer")
    return value


def positive_int(value: Any, *, field: str) -> int:
    parsed = non_negative_int(value, field=field)
    if parsed < 1:
        raise HarnessValidationError(f"{field} must be a positive integer")
    return parsed


def identity(prefix: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    checksum = checksum_for(dict(payload))
    return f"{prefix}://{checksum.removeprefix('sha256:')}", checksum


__all__ = [
    "frozen_mapping",
    "identity",
    "mapping_tuple",
    "non_negative_int",
    "optional_text",
    "positive_int",
    "reject_fields",
    "required_text",
    "strict_payload",
    "text_tuple",
]
