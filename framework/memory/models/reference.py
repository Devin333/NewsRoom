from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryReference:
    ref_type: str
    ref_id: str
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ref_type = str(self.ref_type or "").strip()
        ref_id = str(self.ref_id or "").strip()
        if not ref_type:
            raise ValueError("memory reference ref_type is required")
        if not ref_id:
            raise ValueError("memory reference ref_id is required")
        object.__setattr__(self, "ref_type", ref_type)
        object.__setattr__(self, "ref_id", ref_id)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryReference":
        return cls(
            ref_type=str(payload.get("ref_type") or payload.get("type") or ""),
            ref_id=str(payload.get("ref_id") or payload.get("id") or ""),
            source=_optional_str(payload.get("source")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    def stable_key(self) -> str:
        return f"{self.ref_type}:{self.ref_id}"


def references_from_legacy_refs(refs: dict[str, Any]) -> list[MemoryReference]:
    references: list[MemoryReference] = []
    for key, value in refs.items():
        if value is None:
            continue
        references.append(MemoryReference(ref_type=str(key), ref_id=str(value)))
    return references


def legacy_refs_from_references(values: list[MemoryReference | dict[str, Any]]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for value in values:
        reference = value if isinstance(value, MemoryReference) else MemoryReference.from_dict(dict(value))
        key = reference.ref_type
        if key in refs:
            key = reference.stable_key()
        refs[key] = reference.ref_id
    return refs


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
