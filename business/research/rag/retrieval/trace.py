from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalDegradation:
    code: str
    stage: str
    paper_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "paper_id": self.paper_id,
            "reason": self.reason,
        }


@dataclass
class RetrievalTrace:
    policy_name: str
    policy_hash: str
    route: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    degradations: list[RetrievalDegradation] = field(default_factory=list)

    def append_degradation_once(self, degradation: RetrievalDegradation) -> None:
        if any(
            item.code == degradation.code and item.stage == degradation.stage
            for item in self.degradations
        ):
            return
        self.degradations.append(degradation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "policy_hash": self.policy_hash,
            "route": self.route,
            "stages": list(self.stages),
            "degradations": [item.to_dict() for item in self.degradations],
        }


__all__ = ["RetrievalDegradation", "RetrievalTrace"]
