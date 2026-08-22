from datetime import UTC, datetime

import pytest

from infrastructure.storage.conversation import AgentIterationCheckpoint, AgentMessageRecord, ConversationCursor
from infrastructure.storage.postgres import PostgresConversationStore
from infrastructure.storage.security import REDACTED_VALUE
from infrastructure.storage.postgres.conversation import _upsert_conversation


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
        scope_kind="graph",
        agent_id="analyst",
        run_id="run-1",
        graph_id="test.graph",
        graph_version="1",
        graph_ref="test.graph@1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="agent",
        node_instance_id="agent:1",
        graph_checkpoint_ref="checkpoint://run-1/1",
        activity_id="activity-1",
        attempt=1,
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
    message_insert = next(
        call
        for call in connection.calls
        if "INSERT INTO agent_conversation_messages" in call[0]
    )
    assert message_insert[1][2] == "message-1"
    assert message_insert[1][3] == "assistant"
    assert message_insert[1][4] == '{"text": "hello"}'
    assert message_insert[1][6] == "graph"
    assert message_insert[1][19] == '{"safe": "visible"}'
    assert connection.commits == 1


def test_postgres_conversation_store_reads_messages_and_limits() -> None:
    rows = [
        (
            "message-1",
            "conversation-1",
            "assistant",
            '{"text": "hello"}',
            "2026-05-11T01:00:00Z",
            "graph",
            "analyst",
            "run-1",
            "test.graph",
            "1",
            "test.graph@1",
            "sha256:" + "a" * 64,
            "agent",
            "agent:1",
            "checkpoint://run-1/1",
            "activity-1",
            1,
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
        node_instance_id="agent:1",
        graph_checkpoint_ref="checkpoint://run-1/1",
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
            scope_kind="standalone",
            metadata={"api_key": fake_secret, "safe": "visible"},
        ),
    )

    params = next(
        params
        for sql, params in connection.calls
        if "INSERT INTO agent_conversation_messages" in sql
    )
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


def test_postgres_parent_scope_fence_rejects_cross_graph_message() -> None:
    class ScopedCursor:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def fetchone(self):
            return (
                "graph",
                "run-1",
                "test.graph",
                "1",
                "test.graph@1",
                "sha256:" + "a" * 64,
            )

    cursor = ScopedCursor()
    message = _message()
    forged = AgentMessageRecord(
        **{
            **message.__dict__,
            "graph_version": "2",
            "graph_ref": "test.graph@2",
            "graph_checksum": "sha256:" + "b" * 64,
            "node_instance_id": "agent:2",
            "graph_checkpoint_ref": "checkpoint://run-1/2",
        }
    )

    with pytest.raises(ValueError, match="scope does not match"):
        _upsert_conversation(cursor, "conversation-1", forged)


def test_postgres_graph_state_requires_existing_graph_parent() -> None:
    store = PostgresConversationStore(
        "postgresql://example",
        connection_factory=lambda: FakeConnection(),
    )

    with pytest.raises(ValueError, match="requires an existing exact Graph parent"):
        store.write_cursor(
            ConversationCursor(
                conversation_id="conversation-1",
                message_offset=1,
                message_id="message-1",
                run_id="run-1",
                node_instance_id="agent:1",
                graph_checkpoint_ref="checkpoint://run-1/1",
            )
        )
