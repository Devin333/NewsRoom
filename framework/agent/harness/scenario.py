from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.models import AgentSpec


@dataclass(frozen=True)
class AgentHarnessScenario:
    scenario_id: str
    spec: AgentSpec
    inputs: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "spec": self.spec.to_dict(),
            "inputs": dict(self.inputs),
            "expected": dict(self.expected),
            "metadata": dict(self.metadata),
        }
