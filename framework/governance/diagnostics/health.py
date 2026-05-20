from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.governance.diagnostics.finding import GovernanceFinding
from framework.shared.time import format_datetime, utc_now


@dataclass(frozen=True)
class GovernanceHealthReport:
    status: str
    findings: list[GovernanceFinding] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "generated_at": format_datetime(self.generated_at),
            "metadata": dict(self.metadata),
        }
