from datetime import UTC, datetime

import pytest

from infrastructure.storage.conversation import AgentIterationCheckpoint, AgentMessageRecord, ConversationCursor
from infrastructure.storage.postgres import PostgresConversationStore
from infrastructure.storage.security import REDACTED_VALUE


class FakeCursor:
    def __init__(self, calls, rows):
        self.calls = calls
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows=None):
        self.calls = []
        self.commits = 0
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls, self.rows)

    def commit(self):
        self.commits += 1


def _message(message_id: str = "message-1") -> AgentMessageRecord:
    return AgentMessageRecord(
        message_id=message_id,
        conversation_id="conversation-1",
        role="assistant",
        content={"text": "hello"},
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        agent_id="analyst",
        run_id="run-1",
        step_id="agent",
        metadata={"safe": "visible"},
    )


def test_postgres_conversation_store_appends_message() -> None:
    connection = FakeConnection()
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: connection)

    store.append_message("conversation-1", _message())

    executed = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO agent_conversations" in executed
    assert "INSERT INTO agent_conversation_messages" in executed
    assert "UPDATE agent_conversations" in executed
    assert connection.calls[1][1][2] == "message-1"
    assert connection.calls[1][1][3] == "assistant"
    assert connection.calls[1][1][4] == '{"text": "hello"}'
    assert connection.calls[1][1][10] == '{"safe": "visible"}'
    assert connection.commits == 1


def test_postgres_conversation_store_reads_messages_and_limits() -> None:
    rows = [
        (
            "message-1",
            "conversation-1",
            "assistant",
            '{"text": "hello"}',
            "2026-05-11T01:00:00Z",
            "analyst",
            "run-1",
            "agent",
            True,
            '{"safe": "visible"}',
        )
    ]
    connection = FakeConnection(rows=rows)
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: connection)

    messages = store.read_messages("conversation-1", limit=5)

    assert messages == [_message()]
    assert "FROM agent_conversation_messages" in connection.calls[0][0]
    assert "LIMIT %s" in connection.calls[0][0]
    assert connection.calls[0][1] == ("conversation-1", 5)


def test_postgres_conversation_store_writes_summary_cursor_and_iteration_checkpoint() -> None:
    connection = FakeConnection()
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: connection)

    store.write_summary("conversation-1", "summary")
    store.write_cursor(
        ConversationCursor(
            conversation_id="conversation-1",
            message_offset=1,
            message_id="message-1",
            run_id="run-1",
            step_id="agent",
            updated_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
            metadata={"phase": "draft"},
        )
    )
    store.write_iteration_checkpoint(
        AgentIterationCheckpoint(
            conversation_id="conversation-1",
            agent_id="analyst",
            iteration=1,
            status="accepted",
            diagnostics_summary={"healthy": True},
            updated_at=datetime(2026, 5, 11, 3, 0, tzinfo=UTC),
        )
    )

    executed = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO agent_conversation_state" in executed
    assert "summary = EXCLUDED.summary" in executed
    assert "cursor_json = EXCLUDED.cursor_json" in executed
    assert "iteration_checkpoint_json = EXCLUDED.iteration_checkpoint_json" in executed
    assert connection.commits == 3


def test_postgres_conversation_store_reads_summary_cursor_and_iteration_checkpoint() -> None:
    cursor = ConversationCursor(
        conversation_id="conversation-1",
        message_offset=1,
        message_id="message-1",
        run_id="run-1",
        step_id="agent",
        updated_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
    )
    checkpoint = AgentIterationCheckpoint(
        conversation_id="conversation-1",
        agent_id="analyst",
        iteration=1,
        status="accepted",
        updated_at=datetime(2026, 5, 11, 3, 0, tzinfo=UTC),
    )
    connection = FakeConnection(rows=[("summary",)])
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: connection)

    assert store.get_summary("conversation-1") == "summary"

    connection.rows = [(cursor.to_dict(),)]
    assert store.read_cursor("conversation-1") == cursor

    connection.rows = [(checkpoint.to_dict(),)]
    assert store.read_iteration_checkpoint("conversation-1") == checkpoint


def test_postgres_conversation_store_redacts_message() -> None:
    fake_secret = "sk" + "-postgresconversationsecret123456"
    connection = FakeConnection()
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: connection)

    store.append_message(
        "conversation-1",
        AgentMessageRecord(
            message_id="message-1",
            conversation_id="conversation-1",
            role="assistant",
            content=f"secret {fake_secret}",
            metadata={"api_key": fake_secret, "safe": "visible"},
        ),
    )

    params = connection.calls[1][1]
    assert fake_secret not in str(params)
    assert REDACTED_VALUE in str(params)


def test_postgres_conversation_store_rejects_invalid_inputs() -> None:
    store = PostgresConversationStore("postgresql://example", connection_factory=lambda: FakeConnection())

    with pytest.raises(ValueError, match="invalid conversation_id"):
        store.read_messages("../secret")

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.read_messages("conversation-1", limit=0)

    with pytest.raises(ValueError, match="does not match"):
        store.append_message("other-conversation", _message())
