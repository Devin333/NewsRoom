from __future__ import annotations

from typing import Any


class SubAgentRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, Any] = {}

    def register(self, agent_id: str, executor: Any) -> None:
        agent_id = str(agent_id).strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        self._executors[agent_id] = executor

    def resolve(self, agent_id: str) -> Any:
        try:
            return self._executors[str(agent_id)]
        except KeyError as exc:
            raise KeyError(f"subagent is not registered: {agent_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"agent_ids": sorted(self._executors)}
