from __future__ import annotations

from framework.agent.subagents.executor import SubAgentTask, _child_inputs


def test_subagent_metadata_session_id_is_preserved_in_child_inputs() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="review evidence",
        metadata={"session_id": "session-from-metadata"},
    )

    assert _child_inputs(task)["session_id"] == "session-from-metadata"


def test_subagent_input_session_id_wins_over_metadata() -> None:
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="review evidence",
        inputs={"session_id": "session-from-input"},
        metadata={"session_id": "session-from-metadata"},
    )

    assert _child_inputs(task)["session_id"] == "session-from-input"
