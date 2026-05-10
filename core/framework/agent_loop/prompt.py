from __future__ import annotations

import json
from typing import Any

from core.framework.agent_loop.models import AgentSpec
from core.framework.llm import LLMRequest


class PromptBuilder:
    def build(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        *,
        feedback: str | None = None,
        tool_observations: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMRequest:
        system = agent.system_prompt_template.format(
            role=agent.role,
            instructions=agent.instructions,
        )
        user = agent.task_prompt_template.format(
            goal=agent.goal,
            inputs=json.dumps(inputs, ensure_ascii=False, sort_keys=True),
        )
        if tool_observations:
            user += "\nTool observations: "
            user += json.dumps(tool_observations, ensure_ascii=False, sort_keys=True)
        if feedback:
            user += f"\nJudge feedback: {feedback}"

        return LLMRequest(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=tools or [],
            metadata={"agent_id": agent.agent_id},
        )
