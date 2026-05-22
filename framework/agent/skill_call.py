from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field



class SkillCallParseError(ValueError):
    """Raised when payload.type == skill_call but payload is invalid."""


class SkillCall(BaseModel):
    type: str = "skill_call"
    skill_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None
    reason: str | None = None

    def normalized_name(self) -> str:
        """Lowercase normalized skill name."""
        return self.skill_name.strip().lower()

    def ensure_call_id(self) -> "SkillCall":
        """Return copy with call_id populated as skill_<uuid8> if missing."""
        if self.call_id:
            return self
        return self.model_copy(update={"call_id": f"skill_{uuid4().hex[:8]}"})
