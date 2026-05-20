from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.governance.checks import GateCheckResult
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    passed: bool
    mode: str = "and"
    checks: list[GateCheckResult] = field(default_factory=list)
    failed_dimensions: list[str] = field(default_factory=list)
    decision: str = "pass"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        checks = [
            check if isinstance(check, GateCheckResult) else GateCheckResult.from_dict(check)
            for check in self.checks
        ]
        failed_dimensions = list(
            self.failed_dimensions
            or sorted({check.dimension for check in checks if not check.passed})
        )
        object.__setattr__(self, "checks", checks)
        object.__setattr__(self, "failed_dimensions", failed_dimensions)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def pass_result(
        cls,
        gate_id: str,
        *,
        mode: str = "and",
        checks: list[GateCheckResult] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "GateResult":
        return cls(
            gate_id=gate_id,
            passed=True,
            mode=mode,
            checks=list(checks or []),
            decision="pass",
            reason="gate passed",
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_checks(
        cls,
        gate_id: str,
        checks: list[GateCheckResult],
        *,
        mode: str = "and",
        metadata: dict[str, Any] | None = None,
    ) -> "GateResult":
        blocking = [check for check in checks if check.blocks()]
        failed_dimensions = sorted({check.dimension for check in checks if not check.passed})
        if blocking and mode == "warn_only":
            return cls(
                gate_id=gate_id,
                passed=True,
                mode=mode,
                checks=checks,
                failed_dimensions=failed_dimensions,
                decision="warn",
                reason="; ".join(check.reason for check in blocking if check.reason) or "gate warnings",
                metadata=dict(metadata or {}),
            )
        if blocking:
            return cls(
                gate_id=gate_id,
                passed=False,
                mode=mode,
                checks=checks,
                failed_dimensions=failed_dimensions,
                decision="block",
                reason="; ".join(check.reason for check in blocking if check.reason) or "gate blocked",
                metadata=dict(metadata or {}),
            )
        warnings = [check for check in checks if not check.passed]
        return cls(
            gate_id=gate_id,
            passed=True,
            mode=mode,
            checks=checks,
            failed_dimensions=failed_dimensions,
            decision="warn" if warnings else "pass",
            reason="; ".join(check.reason for check in warnings if check.reason) or "gate passed",
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "mode": self.mode,
            "checks": [check.to_dict() for check in self.checks],
            "failed_dimensions": list(self.failed_dimensions),
            "decision": self.decision,
            "reason": self.reason,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GateResult":
        return cls(
            gate_id=str(payload["gate_id"]),
            passed=bool(payload["passed"]),
            mode=str(payload.get("mode") or "and"),
            checks=[
                GateCheckResult.from_dict(check)
                for check in payload.get("checks") or []
                if isinstance(check, dict)
            ],
            failed_dimensions=[str(item) for item in payload.get("failed_dimensions") or []],
            decision=str(payload.get("decision") or "pass"),
            reason=str(payload.get("reason") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


class CompositeAndGate:
    def __init__(self, gate_id: str, *, mode: str = "and") -> None:
        self.gate_id = gate_id
        self.mode = mode

    def evaluate(
        self,
        checks: list[GateCheckResult],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> GateResult:
        return GateResult.from_checks(
            self.gate_id,
            checks,
            mode=self.mode,
            metadata=metadata,
        )


def gate_summary(gate_result: GateResult | dict[str, Any] | None) -> dict[str, Any] | None:
    if gate_result is None:
        return None
    result = gate_result if isinstance(gate_result, GateResult) else GateResult.from_dict(gate_result)
    return {
        "gate_id": result.gate_id,
        "passed": result.passed,
        "decision": result.decision,
        "failed_dimensions": list(result.failed_dimensions),
        "reason": result.reason,
    }
