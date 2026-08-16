import pytest

from framework.agent.subagents import (
    LocalSubAgentExecutor,
    SubAgentRegistry,
    SubAgentStatus,
    SubAgentTask,
)
from framework.agent.subagents.executor import _child_inputs


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
        SubAgentTask(parent_agent_id="parent", child_agent_id="missing", task="check")
    )

    assert result.success is False
    assert result.status == SubAgentStatus.FAILED
    assert "missing" in result.error


def test_child_inputs_preserve_run_graph_and_ordinary_input_correlation() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="review evidence",
        inputs={"session_id": "domain-input-session"},
        metadata={
            "session_id": "retired-shared-session",
            "run_id": "run-1",
            "graph_id": "graph-1",
        },
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
    )

    assert "session_id" not in _child_inputs(task)
