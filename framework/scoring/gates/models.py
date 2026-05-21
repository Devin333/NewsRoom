from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.scoring.core.models import clamp_score
from framework.shared.json import to_jsonable


class GateAction(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    CAP = "cap"
    PENALTY = "penalty"
    BOOST = "boost"
    REVIEW = "review"


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    action: GateAction
    feature: str | None = None
    operator: str = "exists"
    threshold: float | tuple[float, float] | None = None
    score_cap: float | None = None
    penalty: float = 0.0
    boost: float = 0.0
    severity: str = "warning"
    reason: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        gate_id = str(self.gate_id).strip()
        if not gate_id:
            raise ValueError("gate_id is required")
        action = self.action if isinstance(self.action, GateAction) else GateAction(str(self.action))
        object.__setattr__(self, "gate_id", gate_id)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "feature", str(self.feature) if self.feature is not None else None)
        object.__setattr__(self, "operator", str(self.operator or "exists"))
        object.__setattr__(self, "threshold", _threshold_value(self.threshold))
        object.__setattr__(self, "score_cap", clamp_score(self.score_cap) if self.score_cap is not None else None)
        object.__setattr__(self, "penalty", max(0.0, float(self.penalty or 0.0)))
        object.__setattr__(self, "boost", max(0.0, float(self.boost or 0.0)))
        object.__setattr__(self, "severity", str(self.severity or "warning"))
        object.__setattr__(self, "params", dict(self.params or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "action": self.action.value,
            "feature": self.feature,
            "operator": self.operator,
            "threshold": list(self.threshold) if isinstance(self.threshold, tuple) else self.threshold,
            "score_cap": self.score_cap,
            "penalty": self.penalty,
            "boost": self.boost,
            "severity": self.severity,
            "reason": self.reason,
            "params": to_jsonable(self.params),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GateSpec":
        return cls(
            gate_id=str(payload["gate_id"]),
            action=GateAction(str(payload.get("action") or GateAction.PASS.value)),
            feature=str(payload["feature"]) if payload.get("feature") is not None else None,
            operator=str(payload.get("operator") or "exists"),
            threshold=payload.get("threshold"),
            score_cap=float(payload["score_cap"]) if payload.get("score_cap") is not None else None,
            penalty=float(payload.get("penalty", 0.0)),
            boost=float(payload.get("boost", 0.0)),
            severity=str(payload.get("severity") or "warning"),
            reason=str(payload["reason"]) if payload.get("reason") is not None else None,
            params=dict(payload.get("params") or {}),
        )


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    action: GateAction
    passed: bool
    blocked: bool = False
    review_required: bool = False
    score_cap: float | None = None
    penalty: float = 0.0
    boost: float = 0.0
    reason: str | None = None
    observed: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", self.action if isinstance(self.action, GateAction) else GateAction(str(self.action)))
        object.__setattr__(self, "score_cap", clamp_score(self.score_cap) if self.score_cap is not None else None)
        object.__setattr__(self, "penalty", max(0.0, float(self.penalty or 0.0)))
        object.__setattr__(self, "boost", max(0.0, float(self.boost or 0.0)))
        object.__setattr__(self, "observed", dict(self.observed or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "action": self.action.value,
            "passed": self.passed,
            "blocked": self.blocked,
            "review_required": self.review_required,
            "score_cap": self.score_cap,
            "penalty": self.penalty,
            "boost": self.boost,
            "reason": self.reason,
            "observed": to_jsonable(self.observed),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GateResult":
        return cls(
            gate_id=str(payload["gate_id"]),
            action=GateAction(str(payload.get("action") or GateAction.PASS.value)),
            passed=bool(payload.get("passed", False)),
            blocked=bool(payload.get("blocked", False)),
            review_required=bool(payload.get("review_required", False)),
            score_cap=float(payload["score_cap"]) if payload.get("score_cap") is not None else None,
            penalty=float(payload.get("penalty", 0.0)),
            boost=float(payload.get("boost", 0.0)),
            reason=str(payload["reason"]) if payload.get("reason") is not None else None,
            observed=dict(payload.get("observed") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )


def _threshold_value(value: Any) -> float | tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    return float(value)
