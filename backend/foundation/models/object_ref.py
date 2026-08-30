from __future__ import annotations

from pydantic import field_validator

from backend.foundation.primitives import PrimitiveModel
from backend.foundation.taxonomy import ObjectType


class ObjectRef(PrimitiveModel):
    object_type: ObjectType | str
    object_id: str
    label: str | None = None

    @field_validator("object_type")
    @classmethod
    def _coerce_object_type(cls, value: ObjectType | str) -> ObjectType:
        return ObjectType(value)

    @field_validator("object_id")
    @classmethod
    def _validate_object_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("object_id is required")
        return text


def make_object_ref(object_type: ObjectType | str, object_id: str, *, label: str | None = None) -> ObjectRef:
    return ObjectRef(object_type=object_type, object_id=object_id, label=label)


__all__ = ["ObjectRef", "make_object_ref"]
