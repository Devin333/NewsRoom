import pytest

from framework.agent.subagents import (
    LocalSubAgentExecutor,
    SubAgentRegistry,
    SubAgentStatus,
    SubAgentTask,
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
        SubAgentTask(parent_agent_id="parent", child_agent_id="missing", task="check")
    )

    assert result.success is False
    assert result.status == SubAgentStatus.FAILED
    assert "missing" in result.error
