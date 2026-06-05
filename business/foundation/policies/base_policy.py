from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation.primitives import PrimitiveModel


class BasePolicy(PrimitiveModel):
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["BasePolicy"]
