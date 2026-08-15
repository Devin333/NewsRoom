from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from framework.events.canonical import (
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventCanonicalizationError
from framework.harness.control_plane.errors import HarnessValidationError


_EXACT_REFERENCE_PATTERN = re.compile(
    r"(?P<identifier>[a-zA-Z0-9][a-zA-Z0-9._:/-]*)@(?P<version>[a-zA-Z0-9][a-zA-Z0-9._-]*)\Z"
)
_MOVING_VERSION_ALIASES = frozenset({"current", "default", "latest", "stable"})

T = TypeVar("T")


def required_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise HarnessValidationError(
            f"{field_name} is required",
            code="graph_required_field",
            details={"field": field_name},
        )
    return text


def optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field_name)


def freeze_json(value: Any, field_name: str) -> Any:
    try:
        return normalize_canonical_json(value, path=field_name)
    except EventCanonicalizationError as exc:
        raise HarnessValidationError(
            f"{field_name} must be canonical JSON",
            code="graph_non_canonical_value",
            details={"field": field_name},
        ) from exc


def thaw_json(value: Any) -> Any:
    return thaw_canonical_json(value)


def canonical_checksum(value: Any) -> str:
    try:
        return checksum_for(value)
    except EventCanonicalizationError as exc:
        raise HarnessValidationError(
            "graph checksum input must be canonical JSON",
            code="graph_non_canonical_checksum_input",
        ) from exc


def exact_reference(value: Any, field_name: str) -> str:
    reference = required_text(value, field_name)
    match = _EXACT_REFERENCE_PATTERN.fullmatch(reference)
    if match is None or match.group("version").lower() in _MOVING_VERSION_ALIASES:
        raise HarnessValidationError(
            f"{field_name} must be an exact identifier@version reference",
            code="graph_inexact_version_reference",
            details={"field": field_name, "reference": reference},
        )
    return reference


def stable_unique_tuple(
    values: Sequence[T],
    *,
    field_name: str,
    key,
) -> tuple[T, ...]:
    ordered = tuple(sorted(values, key=key))
    identities = [key(value) for value in ordered]
    duplicates = sorted(
        {identity for identity in identities if identities.count(identity) > 1},
        key=str,
    )
    if duplicates:
        raise HarnessValidationError(
            f"{field_name} must contain unique identities",
            code="graph_duplicate_identity",
            details={"field": field_name, "duplicates": [str(item) for item in duplicates]},
        )
    return ordered


def mapping_to_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    thawed = thaw_json(value)
    if not isinstance(thawed, dict):
        raise AssertionError("canonical mapping did not thaw to dict")
    return thawed


__all__ = [
    "canonical_checksum",
    "exact_reference",
    "freeze_json",
    "mapping_to_dict",
    "optional_text",
    "required_text",
    "stable_unique_tuple",
    "thaw_json",
]
