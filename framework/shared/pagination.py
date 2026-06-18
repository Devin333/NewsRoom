from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from framework.shared.json import to_jsonable

T = TypeVar("T")


@dataclass(frozen=True)
class PageRequest:
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("page limit must be positive")
        if self.limit > 500:
            raise ValueError("page limit must be 500 or less")
        if self.cursor is not None:
            object.__setattr__(self, "cursor", str(self.cursor))

    def to_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "cursor": self.cursor}


@dataclass(frozen=True)
class PageResult(Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None

    def has_more(self) -> bool:
        return self.next_cursor is not None

    def to_dict(
        self,
        item_serializer: Callable[[T], Any] | None = None,
    ) -> dict[str, Any]:
        serializer = item_serializer or to_jsonable
        return {
            "items": [serializer(item) for item in self.items],
            "next_cursor": self.next_cursor,
            "total": self.total,
        }
