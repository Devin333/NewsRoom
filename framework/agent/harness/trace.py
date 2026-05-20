from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.models import AgentLoopResult


@dataclass(frozen=True)
class AgentHarnessTrace:
    scenario_id: str
    result: AgentLoopResult
    evaluation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return bool(self.result.success and self.evaluation.get("passed", True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "success": self.success,
            "result": self.result.to_dict(),
            "evaluation": dict(self.evaluation),
            "metadata": dict(self.metadata),
        }
