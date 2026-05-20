from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.ids import generate_id
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class GovernanceFinding:
    message: str
    severity: str = "info"
    source: str | None = None
    finding_id: str = field(default_factory=lambda: generate_id("finding"))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
            "metadata": to_jsonable(self.metadata),
        }
