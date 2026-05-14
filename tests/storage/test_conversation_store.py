from datetime import UTC, datetime

import pytest

from storage.conversation import AgentMessageRecord, ConversationCursor, LocalJsonConversationStore
from storage.security import REDACTED_VALUE


def _message(message_id: str, role: str, content: str) -> AgentMessageRecord:
    return AgentMessageRecord(
        message_id=message_id,
        conversation_id="conversation-1",
        role=role,
        content=content,
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        agent_id="analyst",
        run_id="run-1",
        step_id="agent_loop",
        metadata={"safe": "visible"},
    )


def test_agent_message_record_round_trips() -> None:
    message = _message("message-1", "user", "Summarize AI policy")

    restored = AgentMessageRecord.from_dict(message.to_dict())

    assert restored == message
    assert restored.to_dict()["created_at"] == "2026-05-11T01:00:00Z"


def test_conversation_cursor_round_trips() -> None:
    cursor = ConversationCursor(
        conversation_id="conversation-1",
        message_offset=3,
        message_id="message-3",
        run_id="run-1",
        step_id="agent",
        workflow_checkpoint_id="cp-1",
        updated_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
        metadata={"phase": "draft"},
    )

    restored = ConversationCursor.from_dict(cursor.to_dict())

    assert restored == cursor
    assert restored.to_dict()["updated_at"] == "2026-05-11T02:00:00Z"


def test_local_json_conversation_store_appends_reads_and_limits(tmp_path) -> None:
    store = LocalJsonConversationStore(tmp_path)
    first = _message("message-1", "user", "First")
    second = _message("message-2", "assistant", "Second")
    third = _message("message-3", "tool", "Third")

    path = store.append_message("conversation-1", first)
    store.append_message("conversation-1", second)
    store.append_message("conversation-1", third)

    assert path.exists()
    assert store.read_messages("conversation-1") == [first, second, third]
    assert store.read_messages("conversation-1", limit=2) == [second, third]


def test_local_json_conversation_store_writes_and_reads_summary(tmp_path) -> None:
    store = LocalJsonConversationStore(tmp_path)

    assert store.get_summary("conversation-1") is None

    path = store.write_summary("conversation-1", "Conversation summary")

    assert path.exists()
    assert store.get_summary("conversation-1") == "Conversation summary"


def test_local_json_conversation_store_writes_and_reads_cursor(tmp_path) -> None:
    store = LocalJsonConversationStore(tmp_path)
    cursor = ConversationCursor(
        conversation_id="conversation-1",
        message_offset=2,
        message_id="message-2",
        run_id="run-1",
        step_id="agent",
        workflow_checkpoint_id="cp-000002-agent",
        updated_at=datetime(2026, 5, 11, 3, 0, tzinfo=UTC),
        metadata={"phase": "draft"},
    )

    assert store.read_cursor("conversation-1") is None

    path = store.write_cursor(cursor)

    assert path.exists()
    assert store.read_cursor("conversation-1") == cursor


def test_local_json_conversation_store_redacts_cursor_metadata(tmp_path) -> None:
    fake_secret = "sk" + "-conversationsecret123456"
    store = LocalJsonConversationStore(tmp_path)

    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-1",
            message_offset=1,
            metadata={"api_key": fake_secret, "safe": "visible"},
        )
    )

    cursor = store.read_cursor("conversation-1")

    assert cursor is not None
    assert cursor.metadata["api_key"] == REDACTED_VALUE
    assert cursor.metadata["safe"] == "visible"
    assert cursor.metadata["redaction_report"]
    assert fake_secret not in str(cursor.to_dict())


def test_local_json_conversation_store_redacts_message_and_summary(tmp_path) -> None:
    fake_secret = "sk" + "-conversationsecret123456"
    store = LocalJsonConversationStore(tmp_path)
    store.append_message(
        "conversation-1",
        AgentMessageRecord(
            message_id="message-1",
            conversation_id="conversation-1",
            role="assistant",
            content=f"Do not persist {fake_secret}",
            metadata={"token": fake_secret, "safe": "visible"},
        ),
    )
    store.write_summary("conversation-1", f"Summary mentions {fake_secret}")

    message = store.read_messages("conversation-1")[0]

    assert fake_secret not in str(message.to_dict())
    assert REDACTED_VALUE in str(message.to_dict())
    assert message.metadata["safe"] == "visible"
    assert message.metadata["token"] == REDACTED_VALUE
    assert message.metadata["redaction_reports"]
    assert fake_secret not in store.get_summary("conversation-1")
    assert REDACTED_VALUE in store.get_summary("conversation-1")


def test_local_json_conversation_store_compacts_messages(tmp_path) -> None:
    fake_secret = "sk" + "-conversationsecret123456"
    store = LocalJsonConversationStore(tmp_path)
    for index, role in enumerate(["user", "tool", "judge", "diagnostic", "assistant"], start=1):
        store.append_message(
            "conversation-1",
            AgentMessageRecord(
                message_id=f"message-{index}",
                conversation_id="conversation-1",
                role=role,
                content={"text": f"Message {index} {fake_secret}"},
                created_at=datetime(2026, 5, 11, index, 0, tzinfo=UTC),
            ),
        )

    record = store.compact_messages("conversation-1", keep_last=2)
    restored = store.get_compaction("conversation-1")

    assert record is not None
    assert restored == record
    assert record.original_message_count == 5
    assert record.compacted_message_count == 3
    assert record.retained_message_count == 2
    assert record.marker_message_id == "compaction-message-3"
    assert record.compacted_until_message_id == "message-3"
    assert record.metadata["retained_message_ids"] == ["message-4", "message-5"]
    assert record.metadata["role_counts"]["judge"] == 1
    assert fake_secret not in record.summary
    assert REDACTED_VALUE in record.summary
    assert store.get_summary("conversation-1") == record.summary
    messages = store.read_messages("conversation-1")
    assert [message.message_id for message in messages] == [
        "compaction-message-3",
        "message-4",
        "message-5",
    ]
    assert messages[0].role == "system"
    assert messages[0].content["summary"] == record.summary
    assert messages[0].metadata["message_type"] == "conversation_compaction"
    assert fake_secret not in str(messages[0].to_dict())


def test_local_json_conversation_store_rejects_invalid_inputs(tmp_path) -> None:
    store = LocalJsonConversationStore(tmp_path)

    with pytest.raises(ValueError, match="invalid conversation_id"):
        store.read_messages("../secret")

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.read_messages("conversation-1", limit=0)

    with pytest.raises(ValueError, match="keep_last must be non-negative"):
        store.compact_messages("conversation-1", keep_last=-1)

    with pytest.raises(ValueError, match="invalid conversation_id"):
        store.read_cursor("../secret")

    with pytest.raises(ValueError, match="invalid message_id"):
        store.write_cursor(
            ConversationCursor(
                conversation_id="conversation-1",
                message_offset=1,
                message_id="../secret",
            )
        )

    with pytest.raises(ValueError, match="message_offset must be non-negative"):
        ConversationCursor(conversation_id="conversation-1", message_offset=-1)

    with pytest.raises(ValueError, match="does not match"):
        store.append_message("other-conversation", _message("message-1", "user", "ok"))

    with pytest.raises(ValueError, match="invalid message_id"):
        store.append_message(
            "conversation-1",
            AgentMessageRecord(
                message_id="../secret",
                conversation_id="conversation-1",
                role="user",
                content="ok",
            ),
        )
