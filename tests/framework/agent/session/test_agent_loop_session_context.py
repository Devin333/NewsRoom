from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSessionContextPolicy, AgentSpec
from framework.agent.session import AgentSharedWorkspace, InMemoryAgentSessionStore
from framework.llm import FakeLLMClient
from framework.tool import ToolExecutor, ToolRegistry


def test_agent_loop_injects_shared_session_context_when_policy_is_enabled() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    workspace.write(
        session_id="session-1",
        run_id="run-1",
        agent_id="writer",
        role="decision",
        content={"answer": "yes"},
        summary="Agent decided yes.",
        confidence=0.9,
    )
    llm = FakeLLMClient([json.dumps({"action_type": "final_output", "output": {"output": {"ok": True}}})])
    agent = AgentSpec(
        agent_id="reader-agent",
        name="Reader Agent",
        instructions="Read shared context.",
        loop_policy=AgentLoopPolicy(max_iterations=1),
        memory_enabled=False,
        session_context_policy=AgentSessionContextPolicy(
            enabled=True,
            roles=("decision",),
            include_content=True,
        ),
    )

    result = AgentLoop(
        llm_client=llm,
        tool_executor=ToolExecutor(ToolRegistry()),
        session_workspace=workspace,
    ).run(agent, {"session_id": "session-1"}, [], run_id="run-1")

    assert result.success is True
    prompt_text = llm.requests[0].estimated_prompt_text()
    assert "shared_agent_session" in prompt_text
    assert "session-1" in prompt_text
    assert "Agent decided yes." in prompt_text
    assert "&quot;answer&quot;: &quot;yes&quot;" in prompt_text
