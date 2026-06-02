from __future__ import annotations

from typing import Any

from framework.agent import AgentOutputBudget


DAILY_AGENT_OUTPUT_BUDGET = AgentOutputBudget(
    max_json_bytes=262_144,
    max_depth=40,
    max_collection_items=5_000,
    max_string_bytes=65_536,
)


def daily_agent_validation_policy() -> dict[str, Any]:
    return {"output_budget": DAILY_AGENT_OUTPUT_BUDGET.to_dict()}
