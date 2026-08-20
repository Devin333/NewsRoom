from __future__ import annotations

import json

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.llm import FakeLLMClient
from framework.memory import InMemoryMemoryStore, MemoryRuntime
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool import ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry


def test_graph_agent_loop_returns_memory_candidates_without_writing_store() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.lookup",
            description="lookup",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        lambda arguments: {"answer": f"found {arguments['query']}"},
    )
    identity = _execution_identity()
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store)
    agent = AgentSpec(
        agent_id="agent-memory-candidate",
        name="Memory Candidate Agent",
        instructions="Use a tool then answer.",
        allowed_tools=["test.lookup"],
        loop_policy=AgentLoopPolicy(max_iterations=3, memory_write_enabled=True),
        tool_policy=ToolPolicy(
            allowed_tools=["test.lookup"],
            require_explicit_allowlist=True,
            require_approval_for_side_effects=False,
        ),
    )
    llm = FakeLLMClient(
        [
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "test.lookup",
                    "tool_args": {"query": "graph memory"},
                }
            ),
            json.dumps(
                {
                    "action_type": "final_output",
                    "output": {"output": {"summary": "done"}},
                }
            ),
        ]
    )

    result = AgentLoop(
        llm_client=llm,
        tool_executor=ToolExecutor(registry, graph_identity=identity),
        memory_runtime=runtime,
    ).run(
        agent,
        {"topic": "graph memory"},
        registry.export_schema_for_llm(agent.agent_id, agent.resolved_tool_policy()),
        run_id=identity.run_id,
        execution_identity=identity,
    )

    assert result.success is True
    assert result.memory_ops == []
    assert store.records() == []
    assert len(result.memory_candidates) == 2
    assert {
        candidate["metadata"]["event_type"]
        for candidate in result.memory_candidates
    } == {"tool_observation", "final_output"}
    for candidate in result.memory_candidates:
        assert candidate["metadata"]["candidate_only"] is True
        assert candidate["metadata"]["graph_identity"] == identity.to_dict()
        assert {
            key: candidate["refs"][key]
            for key in identity.to_dict()
        } == identity.to_dict()


def test_standalone_agent_loop_does_not_forge_graph_memory_candidate() -> None:
    agent = AgentSpec(
        agent_id="standalone-agent",
        name="Standalone Agent",
        instructions="Answer.",
        loop_policy=AgentLoopPolicy(max_iterations=2, memory_write_enabled=True),
    )
    result = AgentLoop(
        llm_client=FakeLLMClient(
            [
                json.dumps(
                        {
                            "action_type": "final_output",
                            "output": {"output": {"summary": "standalone"}},
                        }
                )
            ]
        ),
        tool_executor=ToolExecutor(ToolRegistry()),
    ).run(agent, {"topic": "standalone"}, [], standalone=True)

    assert result.success is True
    assert result.memory_ops == []
    assert result.memory_candidates == []


def _execution_identity() -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id="run-memory-candidate",
        graph_id="research.agent",
        graph_version="2",
        graph_ref="research.agent@2",
        graph_checksum="sha256:" + "a" * 64,
        node_id="analyze",
        node_instance_id="analyze:1",
        activity_id="activity-memory-candidate",
        attempt=1,
    )
