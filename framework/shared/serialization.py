from __future__ import annotations

from typing import Any, Callable, Generic, Protocol, TypeVar

from framework.shared.json import json_loads, stable_json_dumps

T = TypeVar("T")


class Serializable(Protocol):
    def to_dict(self) -> dict[str, Any]:
        ...


class Serializer(Protocol[T]):
    def dumps(self, value: T) -> str:
        ...

    def loads(self, text: str) -> T:
        ...


class JsonDataclassSerializer(Generic[T]):
    def __init__(self, factory: Callable[[dict[str, Any]], T]) -> None:
        self.factory = factory

    def dumps(self, value: T) -> str:
        to_dict = getattr(value, "to_dict", None)
        payload = to_dict() if callable(to_dict) else value
        return stable_json_dumps(payload)

    def loads(self, text: str) -> T:
        payload = json_loads(text)
        if not isinstance(payload, dict):
            raise ValueError("serialized dataclass payload must be an object")
        return self.factory(payload)
