from framework.agent.messages import (
    AgentMessage,
    AgentMessageFormatter,
    AgentMessageRole,
    MessageHistory,
    Scratchpad,
)
from framework.agent.models import AgentAction
from framework.shared.graph_identity import (
    CONVERSATION_SCOPE_GRAPH,
    CONVERSATION_SCOPE_STANDALONE,
)
from datetime import UTC, datetime
import pytest


def test_message_history_scratchpad_and_formatter() -> None:
    history = MessageHistory()
    history.append(AgentMessage(role=AgentMessageRole.USER, content="hello"))
    history.append(AgentMessage.from_dict({"role": "assistant", "content": "hi"}))

    scratchpad = Scratchpad()
    scratchpad.add_thought("inspect")
    scratchpad.add_observation("ok")

    formatter = AgentMessageFormatter()

    assert history.latest(1)[0].content == "hi"
    assert history.to_llm_messages()[0] == {"role": "user", "content": "hello"}
    assert "thought: inspect" in scratchpad.render()
    assert '"action_type": "tool_call"' in formatter.format_action(
        AgentAction.tool_call("memory.recall", {"query": "ai"})
    )


def test_graph_message_record_round_trips_exact_activity_identity() -> None:
    from framework.agent.messages import AgentMessageRecord

    message = AgentMessageRecord(
        conversation_id="conversation-1",
        role="tool",
        content={"status": "ok"},
        scope_kind=CONVERSATION_SCOPE_GRAPH,
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        run_id="run-1",
        graph_id="test.graph",
        graph_version="1",
        graph_ref="test.graph@1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="analyze",
        node_instance_id="analyze:1",
        graph_checkpoint_ref="checkpoint://run-1/1",
        activity_id="activity-1",
        attempt=2,
    )

    restored = AgentMessageRecord.from_dict(message.to_dict())

    assert restored == message
    assert restored.to_dict()["node_instance_id"] == "analyze:1"
    assert restored.to_dict()["attempt"] == 2
    assert restored.to_dict()["scope_kind"] == CONVERSATION_SCOPE_GRAPH
    assert "step_id" not in restored.to_dict()


def test_graph_message_record_rejects_partial_execution_identity() -> None:
    from framework.agent.messages import AgentMessageRecord

    with pytest.raises(ValueError, match="Graph message identity requires"):
        AgentMessageRecord(
            conversation_id="conversation-1",
            role="tool",
            content={},
            scope_kind=CONVERSATION_SCOPE_GRAPH,
            run_id="run-1",
            graph_id="test.graph",
            graph_version="1",
            graph_ref="test.graph@1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="analyze",
            node_instance_id="analyze:1",
            graph_checkpoint_ref="checkpoint://run-1/1",
            activity_id=None,
            attempt=1,
        )


def test_message_record_requires_explicit_standalone_scope_without_graph_fields() -> None:
    from framework.agent.messages import AgentMessageRecord

    standalone = AgentMessageRecord(
        conversation_id="conversation-standalone",
        role="user",
        content={"query": "local"},
        scope_kind=CONVERSATION_SCOPE_STANDALONE,
    )
    assert standalone.to_dict()["scope_kind"] == CONVERSATION_SCOPE_STANDALONE
    assert all(
        standalone.to_dict()[field] is None
        for field in (
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "node_instance_id",
            "activity_id",
            "attempt",
        )
    )

    with pytest.raises(ValueError, match="standalone conversation message"):
        AgentMessageRecord(
            conversation_id="conversation-standalone",
            role="user",
            content={},
            scope_kind=CONVERSATION_SCOPE_STANDALONE,
            run_id="run-1",
        )


def test_message_record_rejects_legacy_step_id_payload() -> None:
    from framework.agent.messages import AgentMessageRecord

    payload = AgentMessageRecord(
        conversation_id="conversation-standalone",
        role="user",
        content={},
        scope_kind=CONVERSATION_SCOPE_STANDALONE,
    ).to_dict()
    payload["step_id"] = "legacy"

    with pytest.raises(ValueError, match="agent message fields are invalid"):
        AgentMessageRecord.from_dict(payload)


def test_conversation_cursor_serializes_graph_outer_identity() -> None:
    from framework.agent.messages import ConversationCursor

    cursor = ConversationCursor(
        conversation_id="conversation-1",
        message_offset=3,
        run_id="run-1",
        node_instance_id="analyze:1",
        graph_checkpoint_ref="checkpoint://run-1/1",
    )

    payload = cursor.to_dict()

    assert payload["run_id"] == "run-1"
    assert payload["node_instance_id"] == "analyze:1"
    assert payload["graph_checkpoint_ref"] == "checkpoint://run-1/1"
