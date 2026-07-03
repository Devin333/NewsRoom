from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvidenceTypeResolver(Protocol):
    """Resolves a retrieved item's content-derived evidence type."""

    def resolve(self, metadata: Mapping[str, Any]) -> str | None:
        """Return an evidence type or None when metadata has no usable signal."""
        ...


class MetadataKeyEvidenceTypeResolver:
    """Deterministic resolver driven by ordered metadata-key mapping tables."""

    def __init__(self, mapping: Mapping[str, Mapping[str, str]]) -> None:
        self._mapping: dict[str, dict[str, str]] = {
            str(key): {str(source): str(target) for source, target in table.items()}
            for key, table in mapping.items()
        }

    def resolve(self, metadata: Mapping[str, Any]) -> str | None:
        for metadata_key, table in self._mapping.items():
            for value in _metadata_values(metadata.get(metadata_key)):
                mapped = table.get(value)
                if mapped:
                    return mapped
        return None


def _metadata_values(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    value = str(raw).strip()
    return (value,) if value else ()


__all__ = [
    "EvidenceTypeResolver",
    "MetadataKeyEvidenceTypeResolver",
]
