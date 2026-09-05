from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from framework.agent.loop.runner import AgentRunner
from framework.agent.models import (
    AgentLoopMetrics,
    AgentLoopResult,
    AgentLoopStatus,
    AgentSpec,
)
from framework.tool import ToolRegistry
from infrastructure.storage.conversation import LocalJsonConversationStore


runner_module = import_module("framework.agent.loop.runner")


class _AcceptedLoop:
    observed_inputs: list[dict[str, Any]] = []

    def __init__(self, **_: Any) -> None:
        pass

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        tools: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        execution_identity: Any | None = None,
        graph_checkpoint_ref: str | None = None,
        standalone: bool = False,
    ) -> AgentLoopResult:
        _ = (
            agent,
            tools,
            run_id,
            execution_identity,
            graph_checkpoint_ref,
            standalone,
        )
        self.observed_inputs.append(dict(inputs))
        return AgentLoopResult(
            success=True,
            status=AgentLoopStatus.ACCEPTED,
            output={"answer": "accepted"},
            iterations=2,
            metrics=AgentLoopMetrics(iterations=2),
            trace={"summary": {"iteration_count": 2}},
            termination_reason="final_output_accepted",
        )


def test_agent_runner_passes_execution_environment_to_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingToolExecutor:
        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(runner_module, "ToolExecutor", _CapturingToolExecutor)
    monkeypatch.setattr(runner_module, "AgentLoop", _AcceptedLoop)
    environment = object()
    runner = AgentRunner(
        llm_client=object(),
        tool_registry=ToolRegistry(),
        execution_environment=environment,
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        instructions="Return a bounded answer.",
    )

    runner.run(agent, {"query": "inspect"}, standalone=True)

    assert captured["execution_environment"] is environment


def test_agent_runner_injects_orchestration_port_into_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingLoop(_AcceptedLoop):
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(runner_module, "AgentLoop", _CapturingLoop)
    port = object()
    runner = AgentRunner(
        llm_client=object(),
        tool_registry=ToolRegistry(),
        orchestration_port=port,
        orchestration_enabled=True,
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        instructions="Return a bounded answer.",
    )

    runner.run(agent, {"query": "inspect"}, standalone=True)

    assert captured["orchestration_port"] is port
    assert captured["orchestration_enabled"] is True


@pytest.fixture
def graph_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> tuple[AgentRunner, LocalJsonConversationStore, AgentSpec]:
    _AcceptedLoop.observed_inputs = []
    monkeypatch.setattr(runner_module, "AgentLoop", _AcceptedLoop)
    store = LocalJsonConversationStore(tmp_path)
    runner = AgentRunner(
        llm_client=object(),
        tool_registry=ToolRegistry(),
        conversation_store=store,
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        instructions="Return a bounded answer.",
    )
    return runner, store, agent


def test_agent_runner_persists_versioned_graph_outer_identity(
    graph_runner,
) -> None:
    runner, store, agent = graph_runner

    runner.run(
        agent,
        {"query": "inspect"},
        conversation_id="conversation-1",
        run_id="run-1",
        graph_id="test.graph",
        graph_version="1",
        graph_ref="test.graph@1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="analyze",
        node_instance_id="analyze:1",
        graph_checkpoint_ref="checkpoint://run-1/7",
        activity_id="activity-1",
        attempt=1,
    )

    cursor = store.read_cursor("conversation-1")
    checkpoint = store.read_iteration_checkpoint("conversation-1")
    assert cursor is not None
    assert checkpoint is not None
    assert (
        cursor.run_id,
        cursor.node_instance_id,
        cursor.graph_checkpoint_ref,
    ) == ("run-1", "analyze:1", "checkpoint://run-1/7")
    assert (
        checkpoint.run_id,
        checkpoint.node_instance_id,
        checkpoint.graph_checkpoint_ref,
    ) == ("run-1", "analyze:1", "checkpoint://run-1/7")
    assert cursor.schema_version == "newsroom.graph-conversation-cursor/v2"
    assert (
        checkpoint.schema_version
        == "newsroom.graph-agent-iteration-checkpoint/v2"
    )
    assert "workflow_checkpoint_id" not in cursor.to_dict()
    assert "step_id" not in checkpoint.to_dict()


def test_agent_runner_does_not_masquerade_standalone_run_as_graph_identity(
    graph_runner,
) -> None:
    runner, store, agent = graph_runner

    runner.run(
        agent,
        {"query": "inspect"},
        conversation_id="conversation-standalone",
        run_id="standalone-run",
        standalone=True,
    )

    cursor = store.read_cursor("conversation-standalone")
    checkpoint = store.read_iteration_checkpoint("conversation-standalone")
    assert cursor is not None
    assert checkpoint is not None
    assert (cursor.run_id, cursor.node_instance_id, cursor.graph_checkpoint_ref) == (
        None,
        None,
        None,
    )
    assert (
        checkpoint.run_id,
        checkpoint.node_instance_id,
        checkpoint.graph_checkpoint_ref,
    ) == (None, None, None)


def test_agent_runner_rejects_graph_identity_declared_as_standalone(
    graph_runner,
) -> None:
    runner, _, agent = graph_runner

    with pytest.raises(ValueError, match="standalone.*cannot carry Graph identity"):
        runner.run(
            agent,
            {"query": "inspect"},
            conversation_id="conversation-invalid-scope",
            run_id="run-1",
            graph_id="test.graph",
            graph_version="1",
            graph_ref="test.graph@1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="analyze",
            node_instance_id="analyze:1",
            graph_checkpoint_ref="checkpoint://run-1/7",
            activity_id="activity-1",
            attempt=1,
            standalone=True,
        )


def test_agent_runner_injects_only_matching_graph_resume_context(
    graph_runner,
) -> None:
    runner, _, agent = graph_runner
    identity = {
        "run_id": "run-1",
        "graph_id": "test.graph",
        "graph_version": "1",
        "graph_ref": "test.graph@1",
        "graph_checksum": "sha256:" + "a" * 64,
        "node_id": "analyze",
        "node_instance_id": "analyze:1",
        "graph_checkpoint_ref": "checkpoint://run-1/7",
        "activity_id": "activity-1",
        "attempt": 1,
    }
    runner.run(
        agent,
        {"query": "first"},
        conversation_id="conversation-resume",
        **identity,
    )

    runner.run(
        agent,
        {"query": "resume"},
        conversation_id="conversation-resume",
        resume_from_cursor=True,
        **identity,
    )

    resumed_inputs = _AcceptedLoop.observed_inputs[-1]
    assert resumed_inputs["conversation_cursor"]["node_instance_id"] == "analyze:1"
    assert (
        resumed_inputs["agent_iteration_checkpoint"]["graph_checkpoint_ref"]
        == "checkpoint://run-1/7"
    )

    with pytest.raises(ValueError, match="Graph identity mismatch"):
        runner.run(
            agent,
            {"query": "forged resume"},
            conversation_id="conversation-resume",
            run_id="run-1",
            graph_id="test.graph",
            graph_version="1",
            graph_ref="test.graph@1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="analyze",
            node_instance_id="other:1",
            graph_checkpoint_ref="checkpoint://run-1/7",
            activity_id="activity-1",
            attempt=1,
            resume_from_cursor=True,
        )


def test_agent_runner_rejects_partial_graph_identity(graph_runner) -> None:
    runner, _, agent = graph_runner

    with pytest.raises(ValueError, match="requires run_id, node_instance_id"):
        runner.run(
            agent,
            {"query": "inspect"},
            conversation_id="conversation-invalid",
            run_id="run-1",
            node_instance_id="analyze:1",
        )

    with pytest.raises(ValueError, match="graph_checkpoint_ref"):
        runner.run(
            agent,
            {"query": "inspect"},
            conversation_id="conversation-invalid",
            run_id="run-1",
            node_instance_id="analyze:1",
            graph_checkpoint_ref="checkpoint://run-1/1\nforged",
        )
