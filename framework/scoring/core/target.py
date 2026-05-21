from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class TargetRef:
    ref_id: str
    ref_type: str
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ref_id = str(self.ref_id).strip()
        ref_type = str(self.ref_type).strip()
        if not ref_id or not ref_type:
            raise ValueError("target ref id and type are required")
        object.__setattr__(self, "ref_id", ref_id)
        object.__setattr__(self, "ref_type", ref_type)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "ref_type": self.ref_type,
            "label": self.label,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TargetRef":
        return cls(
            ref_id=str(payload["ref_id"]),
            ref_type=str(payload["ref_type"]),
            label=str(payload["label"]) if payload.get("label") is not None else None,
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScoringTarget:
    target_id: str
    target_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    refs: list[TargetRef] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        target_id = str(self.target_id).strip()
        target_type = str(self.target_type).strip()
        if not target_id or not target_type:
            raise ValueError("scoring target id and type are required")
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "payload", dict(self.payload or {}))
        object.__setattr__(
            self,
            "refs",
            [ref if isinstance(ref, TargetRef) else TargetRef.from_dict(dict(ref)) for ref in self.refs],
        )
        object.__setattr__(self, "tags", [str(tag) for tag in self.tags])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_object(
        cls,
        obj: Any,
        *,
        target_id: str | None = None,
        target_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ScoringTarget":
        actual_id = target_id or _first_attr(obj, "target_id", "card_id", "id", "source_id", "memory_id")
        actual_type = target_type or _object_type(obj)
        payload = _object_payload(obj)
        return cls(
            target_id=str(actual_id),
            target_type=str(actual_type),
            payload=payload,
            metadata=dict(metadata or {}),
        )

    def get_payload_value(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "payload": to_jsonable(self.payload),
            "refs": [ref.to_dict() for ref in self.refs],
            "tags": list(self.tags),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringTarget":
        return cls(
            target_id=str(payload["target_id"]),
            target_type=str(payload["target_type"]),
            payload=dict(payload.get("payload") or {}),
            refs=[TargetRef.from_dict(dict(ref)) for ref in payload.get("refs") or []],
            tags=[str(tag) for tag in payload.get("tags") or []],
            metadata=dict(payload.get("metadata") or {}),
        )


def _first_attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value:
            return value
    raise ValueError("target_id is required when object has no id-like attribute")


def _object_type(obj: Any) -> str:
    board_type = getattr(obj, "board_type", None)
    if board_type is not None:
        value = getattr(board_type, "value", board_type)
        return str(value)
    primary = getattr(obj, "primary_object_ref", None)
    object_type = getattr(primary, "object_type", None)
    if object_type is not None:
        return str(getattr(object_type, "value", object_type))
    return type(obj).__name__


def _object_payload(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {
        name: to_jsonable(value)
        for name, value in vars(obj).items()
        if not name.startswith("_")
    }
