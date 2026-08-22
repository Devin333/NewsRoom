import json

import pytest

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentSpec
from framework.agent.subagents import (
    LocalSubAgentExecutor,
    SubAgentRegistry,
    SubAgentResult,
    SubAgentStatus,
    SubAgentTask,
)
from framework.agent.subagents.executor import _child_inputs
from framework.llm import FakeLLMClient
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool import ToolExecutor, ToolRegistry


IDENTITY = GraphExecutionIdentity(
    run_id="run-1",
    graph_id="graph-1",
    graph_version="1",
    graph_ref="graph-1@1",
    graph_checksum="sha256:" + "a" * 64,
    node_id="parent",
    node_instance_id="parent:1",
    activity_id="activity-1",
    attempt=1,
)


def test_subagent_registry_resolves_registered_executor() -> None:
    executor = object()
    registry = SubAgentRegistry()

    registry.register("critic", executor)

    assert registry.resolve("critic") is executor
    assert registry.to_dict() == {"agent_ids": ["critic"]}
    with pytest.raises(KeyError):
        registry.resolve("missing")


def test_local_subagent_executor_execute_alias_reports_missing_child() -> None:
    executor = LocalSubAgentExecutor(agents={}, llm_client=object(), tool_registry=object())

    result = executor.execute(
        SubAgentTask(
            parent_agent_id="parent",
            child_agent_id="missing",
            task="check",
            standalone=True,
        )
    )

    assert result.success is False
    assert result.status == SubAgentStatus.FAILED
    assert "missing" in result.error


def test_child_inputs_preserve_verified_graph_and_ordinary_input_correlation() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="review evidence",
        inputs={"session_id": "domain-input-session"},
        metadata={"session_id": "retired-shared-session"},
        execution_identity=IDENTITY,
        graph_checkpoint_ref="checkpoint://run-1/1",
    )

    assert _child_inputs(task) == {
        "subagent_task": "review evidence",
        "handoff_reason": None,
        "parent_agent_id": "parent",
        "session_id": "domain-input-session",
        "run_id": "run-1",
        "graph_id": "graph-1",
    }


def test_child_inputs_do_not_promote_metadata_session_id() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="review evidence",
        metadata={"session_id": "retired-shared-session"},
        standalone=True,
    )

    assert "session_id" not in _child_inputs(task)


def test_subagent_task_requires_exact_graph_or_explicit_standalone_scope() -> None:
    with pytest.raises(ValueError, match="requires an exact GraphExecutionIdentity"):
        SubAgentTask(parent_agent_id="parent", child_agent_id="child", task="check")

    with pytest.raises(ValueError, match="graph_checkpoint_ref"):
        SubAgentTask(
            parent_agent_id="parent",
            child_agent_id="child",
            task="check",
            execution_identity=IDENTITY,
        )

    with pytest.raises(ValueError, match="standalone.*cannot carry Graph identity"):
        SubAgentTask(
            parent_agent_id="parent",
            child_agent_id="child",
            task="check",
            execution_identity=IDENTITY,
            graph_checkpoint_ref="checkpoint://run-1/1",
            standalone=True,
        )


def test_subagent_task_does_not_promote_graph_identity_from_metadata() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="check",
        metadata={"run_id": "forged-run", "graph_id": "forged-graph"},
        standalone=True,
    )

    child_inputs = _child_inputs(task)
    assert "run_id" not in child_inputs
    assert "graph_id" not in child_inputs


@pytest.mark.parametrize("standalone", [False, True])
def test_agent_loop_delegation_inherits_validated_parent_scope(
    standalone: bool,
) -> None:
    recorded: list[SubAgentTask] = []

    class _Executor:
        def run(self, task: SubAgentTask) -> SubAgentResult:
            recorded.append(task)
            return SubAgentResult(
                child_agent_id=task.child_agent_id,
                success=True,
                output={"review": "accepted"},
            )

        execute = run

    agent = AgentSpec(
        agent_id="parent",
        name="Parent",
        instructions="Delegate once and return the result.",
        loop_policy=AgentLoopPolicy(max_iterations=3, allow_subagents=True),
        allowed_subagents=["critic"],
    )
    loop = AgentLoop(
        llm_client=FakeLLMClient(
            [
                json.dumps(
                    {
                        "action_type": "delegate",
                        "agent_id": "critic",
                        "task": "review evidence",
                    }
                ),
                json.dumps(
                        {
                            "action_type": "final_output",
                            "output": {"output": {"summary": "reviewed"}},
                        }
                ),
            ]
        ),
        tool_executor=ToolExecutor(
            ToolRegistry(),
            graph_identity=None if standalone else IDENTITY,
        ),
        subagent_executor=_Executor(),
    )

    result = loop.run(
        agent,
        {"topic": "evidence"},
        [],
        run_id="standalone-run" if standalone else IDENTITY.run_id,
        execution_identity=None if standalone else IDENTITY,
        graph_checkpoint_ref=(
            None if standalone else "checkpoint://run-1/1"
        ),
        standalone=standalone,
    )

    assert result.success is True
    assert len(recorded) == 1
    task = recorded[0]
    assert task.standalone is standalone
    assert task.execution_identity is (None if standalone else IDENTITY)
    assert task.graph_checkpoint_ref == (
        None if standalone else "checkpoint://run-1/1"
    )
