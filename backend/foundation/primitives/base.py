from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PrimitiveModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


__all__ = ["PrimitiveModel"]
