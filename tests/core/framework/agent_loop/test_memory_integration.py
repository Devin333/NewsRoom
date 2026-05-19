from core.framework.agent_loop import AgentRunner, AgentSpec
from core.framework.llm import FakeLLMClient
from core.framework.memory import (
    DEFAULT_AGENT_MEMORY_POLICY,
    InMemoryMemoryStore,
    MemoryRecord,
    MemoryRuntime,
)
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
                    refs={"run_id": "run-1"},
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
    ).run(agent, {"topic": "runtime latency", "run_id": "run-1"})

    assert result.success is True
    assert "Memory context:" in llm.requests[0].messages[1]["content"]
    assert "latency budget" in llm.requests[0].messages[1]["content"]


def test_default_agent_memory_policy_is_recall_only_and_ref_backed() -> None:
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_write is False
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_recall is True
    assert DEFAULT_AGENT_MEMORY_POLICY.require_refs is True
    assert DEFAULT_AGENT_MEMORY_POLICY.max_recall_results == 5
    assert DEFAULT_AGENT_MEMORY_POLICY.max_context_tokens == 1500
