from core.framework.agent_loop import AgentRunner, AgentSpec
from core.framework.llm import FakeLLMClient
from core.framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime
from core.framework.tools.registry import ToolRegistry


def test_agent_runner_injects_memory_context_before_llm_call() -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-latency",
                    content="Use the latency budget when evaluating runtime changes.",
                    scope="agent",
                    kind="semantic",
                    metadata={"agent_id": "analyst"},
                )
            ]
        )
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["topic"],
        output_key="analysis_result",
        output_schema={
            "type": "object",
            "required": ["analysis_result"],
            "properties": {"analysis_result": {"type": "object"}},
        },
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=ToolRegistry(),
        memory_runtime=runtime,
    ).run(agent, {"topic": "runtime latency"})

    assert result.success is True
    assert "Memory context:" in llm.requests[0].messages[1]["content"]
    assert "latency budget" in llm.requests[0].messages[1]["content"]

