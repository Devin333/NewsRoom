from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from collections.abc import Mapping


DEFAULT_INLINE_PAYLOAD_BYTES = 64 * 1024


class FieldDisposition(StrEnum):
    ALLOWED = "allowed"
    SENSITIVE = "sensitive"
    REFERENCE_ONLY = "reference_only"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class SensitivityPolicy:
    """Schema-owned policy for values crossing the durable boundary.

    Paths use JSON Pointer syntax (for example ``/headers/authorization``).
    Key-name fallback checks in the projector are exact matches, never
    substring heuristics.
    """

    field_rules: Mapping[str, FieldDisposition | str] = field(default_factory=dict)
    allow_payload_reference: bool = False
    redact_sensitive: bool = False
    max_inline_payload_bytes: int = DEFAULT_INLINE_PAYLOAD_BYTES

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_inline_payload_bytes, bool)
            or not isinstance(self.max_inline_payload_bytes, int)
            or self.max_inline_payload_bytes <= 0
        ):
            raise ValueError("max_inline_payload_bytes must be positive")
        if not isinstance(self.allow_payload_reference, bool):
            raise TypeError("allow_payload_reference must be a bool")
        if not isinstance(self.redact_sensitive, bool):
            raise TypeError("redact_sensitive must be a bool")
        if not isinstance(self.field_rules, Mapping):
            raise TypeError("field_rules must be a mapping")
        normalized: dict[str, FieldDisposition] = {}
        for raw_path, raw_disposition in self.field_rules.items():
            path = _normalize_pointer(raw_path)
            if path in normalized:
                raise ValueError(f"duplicate sensitivity path: {path}")
            normalized[path] = FieldDisposition(raw_disposition)
        object.__setattr__(self, "field_rules", MappingProxyType(normalized))

    def disposition_for(self, path: str) -> FieldDisposition:
        normalized = _normalize_pointer(path)
        exact = self.field_rules.get(normalized)
        if exact is not None:
            return exact
        if normalized:
            wildcard = "/".join(
                "*" if segment.isdecimal() else segment
                for segment in normalized.split("/")
            )
            matched = self.field_rules.get(wildcard)
            if matched is not None:
                return matched
        return FieldDisposition.ALLOWED

    @property
    def has_reference_only_fields(self) -> bool:
        return any(
            disposition is FieldDisposition.REFERENCE_ONLY
            for disposition in self.field_rules.values()
        )

    def permits_ordinary_reference(self, *, size_bytes: int | None) -> bool:
        """Return whether a non-sensitive reference proves the inline limit was exceeded."""

        if not self.allow_payload_reference:
            return False
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            return False
        return size_bytes > self.max_inline_payload_bytes


def _normalize_pointer(path: str) -> str:
    if not isinstance(path, str):
        raise TypeError("sensitivity path must be a string")
    text = path.strip()
    if not text or text == "/":
        return ""
    if text.startswith("$."):
        text = "/" + "/".join(part for part in text[2:].split(".") if part)
    if not text.startswith("/"):
        text = f"/{text}"
    return text.rstrip("/")
