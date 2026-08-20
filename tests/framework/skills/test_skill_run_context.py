from __future__ import annotations

from framework.skills import SkillRunContext
from framework.shared import GraphStageIdentity


def test_skill_run_context_factories() -> None:
    test_context = SkillRunContext.for_test("runnable-skill")
    graph_context = SkillRunContext.for_graph(
        "runnable-skill",
        GraphStageIdentity(
            run_id="graph-run",
            graph_id="test.graph",
            graph_version="1",
            graph_ref="test.graph@1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="analyze",
            node_instance_id="node-1",
        ),
    )
    agent_context = SkillRunContext.for_agent("runnable-skill", "agent-run", "call-1")

    assert test_context.run_id == "test-run"
    assert test_context.caller_type == "test"
    assert graph_context.caller_type == "graph"
    assert graph_context.caller_id == "node-1"
    assert graph_context.metadata["graph_identity"]["graph_ref"] == "test.graph@1"
    assert agent_context.caller_type == "agent"
    assert agent_context.caller_id == "call-1"
    assert agent_context.metadata == {"agent_run_id": "agent-run", "call_id": "call-1"}
