from __future__ import annotations

from dataclasses import fields
import inspect

from framework.agent.loop.runner import AgentRunner
from framework.agent.messages import AgentMessageRecord as FrameworkMessageRecord
from framework.agent.messages import (
    AgentIterationCheckpoint as FrameworkIterationCheckpoint,
)
from framework.agent.messages import ConversationCursor as FrameworkConversationCursor
from infrastructure.storage.conversation import (
    AgentIterationCheckpoint as StorageIterationCheckpoint,
    AgentMessageRecord as StorageMessageRecord,
)
from infrastructure.storage.conversation import (
    ConversationCursor as StorageConversationCursor,
)
from tests.architecture._helpers import PROJECT_ROOT


LIVE_CONVERSATION_STATE_FILES = (
    PROJECT_ROOT / "framework" / "agent" / "loop" / "runner.py",
    PROJECT_ROOT / "framework" / "agent" / "subagents" / "executor.py",
    PROJECT_ROOT / "framework" / "workflow" / "runners" / "agent_loop.py",
    PROJECT_ROOT / "infrastructure" / "storage" / "conversation" / "local_json.py",
    PROJECT_ROOT / "infrastructure" / "storage" / "postgres" / "conversation.py",
)


def test_live_conversation_state_has_only_graph_checkpoint_identity() -> None:
    for model in (
        FrameworkConversationCursor,
        FrameworkIterationCheckpoint,
        StorageConversationCursor,
        StorageIterationCheckpoint,
    ):
        model_fields = {item.name for item in fields(model)}
        assert {
            "schema_version",
            "run_id",
            "node_instance_id",
            "graph_checkpoint_ref",
        }.issubset(model_fields)
        assert "step_id" not in model_fields
        assert "workflow_checkpoint_id" not in model_fields
        assert "workflow_checkpoint_id" not in inspect.getsource(model.to_dict)
        assert "workflow_checkpoint_id" not in inspect.getsource(model.from_dict)


def test_live_conversation_messages_use_discriminated_scope_without_step_id() -> None:
    for model in (FrameworkMessageRecord, StorageMessageRecord):
        model_fields = {item.name for item in fields(model)}
        assert "scope_kind" in model_fields
        assert "step_id" not in model_fields
        assert "step_id" not in inspect.getsource(model.to_dict)
        assert "step_id" not in inspect.getsource(model.from_dict)

    runner_parameters = set(inspect.signature(AgentRunner.run).parameters)
    assert "step_id" not in runner_parameters


def test_agent_runner_accepts_graph_identity_and_retires_workflow_checkpoint() -> None:
    run_parameters = set(inspect.signature(AgentRunner.run).parameters)

    assert {"run_id", "node_instance_id", "graph_checkpoint_ref"}.issubset(
        run_parameters
    )
    assert "workflow_checkpoint_id" not in run_parameters


def test_live_conversation_state_writers_do_not_restore_workflow_checkpoint() -> None:
    violations = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in LIVE_CONVERSATION_STATE_FILES
        if path.exists()
        and "workflow_checkpoint_id" in path.read_text(encoding="utf-8")
    ]

    assert violations == []
