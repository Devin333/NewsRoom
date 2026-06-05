from __future__ import annotations

from hashlib import sha1
from typing import Any

from pydantic import BaseModel, field_validator

from business.foundation.primitives.base import PrimitiveModel


class BusinessId(PrimitiveModel):
    value: str
    namespace: str

    @field_validator("value", "namespace")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("business id fields must be non-empty")
        return text

    @classmethod
    def stable(cls, namespace: str, *parts: Any, prefix: str | None = None) -> "BusinessId":
        return cls(namespace=normalize_key(namespace), value=build_stable_id(prefix or namespace, *parts))


def build_stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    normalized = "|".join(_normalize_part(part) for part in parts)
    digest = sha1(normalized.encode("utf-8")).hexdigest()[:length]
    clean_prefix = normalize_key(prefix) or "id"
    return f"{clean_prefix}_{digest}"


def normalize_key(text: str) -> str:
    value = str(text).strip().casefold()
    value = value.replace("&", " and ")
    value = "".join(ch if ch.isalnum() else "_" for ch in value)
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_")


def slugify(text: str) -> str:
    value = normalize_key(text)
    return value.replace("_", "-")


def stable_business_id(namespace: str, *parts: Any, prefix: str | None = None) -> BusinessId:
    return BusinessId.stable(namespace, *parts, prefix=prefix)


def _normalize_part(part: Any) -> str:
    if isinstance(part, BaseModel):
        return repr(part.model_dump(mode="json", exclude_none=True))
    if isinstance(part, dict):
        return repr(sorted((str(key), _normalize_part(value)) for key, value in part.items()))
    if isinstance(part, (list, tuple, set)):
        return repr([_normalize_part(value) for value in part])
    return str(part).strip().casefold()


__all__ = [
    "BusinessId",
    "build_stable_id",
    "normalize_key",
    "slugify",
    "stable_business_id",
]
