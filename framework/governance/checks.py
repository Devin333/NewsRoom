from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class GateCheckResult:
    check_id: str
    dimension: str
    passed: bool
    severity: str = "error"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "check_id", str(self.check_id))
        object.__setattr__(self, "dimension", str(self.dimension))
        object.__setattr__(self, "severity", str(self.severity))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def blocks(self) -> bool:
        return not self.passed and self.severity in {"error", "critical"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "dimension": self.dimension,
            "passed": self.passed,
            "severity": self.severity,
            "reason": self.reason,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GateCheckResult":
        return cls(
            check_id=str(payload["check_id"]),
            dimension=str(payload["dimension"]),
            passed=bool(payload["passed"]),
            severity=str(payload.get("severity") or "error"),
            reason=str(payload.get("reason") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )
