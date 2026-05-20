from __future__ import annotations

from typing import Any


class AgentPlanner:
    """Small planning hook for PRD-facing loop integrations."""

    def plan_next(self, state: Any) -> dict[str, Any]:
        iteration = getattr(state, "iteration", None)
        action = getattr(state, "last_action", None)
        return {
            "iteration": iteration,
            "has_last_action": action is not None,
            "next": "continue",
        }
