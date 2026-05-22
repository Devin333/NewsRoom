from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AcceptanceCheck:
    check_id: str
    area: str
    passed: bool
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceResult:
    run_id: str
    status: str
    checks: list[AcceptanceCheck]
    artifact_root: str
    summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_checks(
        cls,
        *,
        run_id: str,
        checks: list[AcceptanceCheck],
        artifact_root: str,
        summary: dict[str, Any] | None = None,
    ) -> "AcceptanceResult":
        return cls(
            run_id=run_id,
            status=_status(checks),
            checks=list(checks),
            artifact_root=artifact_root,
            summary={
                "check_count": len(checks),
                "passed_count": sum(1 for check in checks if check.passed),
                "failed_count": sum(1 for check in checks if not check.passed),
                **dict(summary or {}),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "artifact_root": self.artifact_root,
            "summary": dict(self.summary),
        }


def _status(checks: list[AcceptanceCheck]) -> str:
    if checks and all(check.passed for check in checks):
        return "passed"
    if checks and not any(check.passed for check in checks):
        return "failed"
    return "partial"


__all__ = ["AcceptanceCheck", "AcceptanceResult"]
