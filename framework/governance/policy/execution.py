from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionPolicy:
    enabled: bool = True
    disabled_reason: str | None = None

    def can_execute(self, context: Any) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, self.disabled_reason or "execution disabled"
        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
        }
