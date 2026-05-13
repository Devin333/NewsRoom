from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Pagination(BaseModel):
    limit: int = Field(default=20, ge=1)
    cursor: str | None = None


class PageResult(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    total_estimate: int | None = None


class ApiActionResult(BaseModel):
    action: str
    resource_type: str
    resource_id: str | None = None
    status: str
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump() if hasattr(self, "model_dump") else self.dict()
