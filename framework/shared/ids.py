from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from framework.shared.errors import ValidationError
from framework.shared.hashing import short_hash

_INVALID_ID_CHARS = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class RunId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", normalize_id(self.value))

    def __str__(self) -> str:
        return self.value

    @classmethod
    def new(cls, prefix: str = "run") -> RunId:
        return cls(generate_id(prefix))


@dataclass(frozen=True)
class StepId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", normalize_id(self.value))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TaskId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", normalize_id(self.value))

    def __str__(self) -> str:
        return self.value


def generate_id(prefix: str) -> str:
    return f"{_normalize_prefix(prefix)}_{uuid.uuid4().hex}"


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    return f"{_normalize_prefix(prefix)}_{short_hash(payload)}"


def normalize_id(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValidationError("id value is required", code="invalid_id")
    return normalized


def _normalize_prefix(prefix: str) -> str:
    normalized = _INVALID_ID_CHARS.sub("_", str(prefix).strip()).strip("_.-")
    if not normalized:
        raise ValidationError("id prefix is required", code="invalid_id_prefix")
    return normalized
