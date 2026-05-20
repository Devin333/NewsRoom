from core.framework.agent_loop import AgentRunner, AgentSpec
from framework.llm import FakeLLMClient
from core.framework.memory import (
    DEFAULT_AGENT_MEMORY_POLICY,
    DEFAULT_AGENT_MEMORY_WRITE_POLICY,
    InMemoryMemoryStore,
    MemoryQuery,
    MemoryRecord,
    MemoryRuntime,
)
from framework.tool.models import ToolDefinition
from framework.tool.registry import ToolRegistry


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


def test_agent_runner_writes_final_output_memory_after_acceptance() -> None:
    llm = FakeLLMClient(
        ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
    )
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store)
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
    ).run(agent, {"topic": "runtime latency"}, run_id="run-accepted")

    assert result.success is True
    memories = store.search(
        MemoryQuery(
            query="Final output",
            scopes=["agent"],
            kinds=["episodic"],
            filters={"agent_id": "analyst", "run_id": "run-accepted"},
        )
    )
    assert len(memories) == 1
    record = memories[0].record
    assert record.summary == "Final output from analyst"
    assert record.refs["run_id"] == "run-accepted"
    assert "analysis_result" in record.content


def test_agent_runner_writes_tool_observation_memory_with_agent_write_policy() -> None:
    llm = FakeLLMClient(
        [
            '{"action_type":"tool_call","tool_name":"memory.search","tool_args":{"query":"latency"}}',
            '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
        ]
    )
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: {"matches": [{"title": args["query"]}]},
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["topic"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
        output_schema={
            "type": "object",
            "required": ["analysis_result"],
            "properties": {"analysis_result": {"type": "object"}},
        },
    )

    result = AgentRunner(
        llm_client=llm,
        tool_registry=registry,
        memory_runtime=runtime,
    ).run(agent, {"topic": "runtime latency"}, run_id="run-tool")

    assert result.success is True
    memories = store.search(
        MemoryQuery(
            query="Tool observation",
            scopes=["agent"],
            kinds=["observation"],
            filters={"agent_id": "analyst", "run_id": "run-tool"},
        )
    )
    assert len(memories) == 1
    record = memories[0].record
    assert record.summary == "Tool observation from memory.search"
    assert record.refs["run_id"] == "run-tool"
    assert record.metadata["tool_name"] == "memory.search"


def test_default_agent_memory_policy_is_recall_only_and_ref_backed() -> None:
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_write is False
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_recall is True
    assert DEFAULT_AGENT_MEMORY_POLICY.require_refs is True
    assert DEFAULT_AGENT_MEMORY_POLICY.max_recall_results == 5
    assert DEFAULT_AGENT_MEMORY_POLICY.max_context_tokens == 1500


def test_default_agent_memory_write_policy_is_hook_only_and_ref_backed() -> None:
    assert DEFAULT_AGENT_MEMORY_WRITE_POLICY.allow_write is True
    assert DEFAULT_AGENT_MEMORY_WRITE_POLICY.allow_recall is False
    assert DEFAULT_AGENT_MEMORY_WRITE_POLICY.require_refs is True
    assert [scope.value for scope in DEFAULT_AGENT_MEMORY_WRITE_POLICY.allowed_scopes] == [
        "session",
        "agent",
        "workflow",
    ]
    assert [kind.value for kind in DEFAULT_AGENT_MEMORY_WRITE_POLICY.allowed_kinds] == [
        "episodic",
        "observation",
    ]

