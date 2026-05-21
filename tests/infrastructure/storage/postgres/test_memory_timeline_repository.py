from datetime import UTC, datetime

from business.memory.intelligence_models import ClaimHistoryRecord, EventMemory
from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository
from infrastructure.storage.postgres.repository import PostgresRepository


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))

    def fetchone(self):
        if self.connection.one_rows:
            return self.connection.one_rows.pop(0)
        return None

    def fetchall(self):
        if self.connection.all_rows:
            return self.connection.all_rows.pop(0)
        return []


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.one_rows = []
        self.all_rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def test_postgres_memory_repository_lists_events_by_topic_and_entity() -> None:
    connection = FakeConnection()
    event_row = _event_row("event-1")
    connection.all_rows = [[event_row], [event_row]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    by_topic = repository.list_events_by_topic("AI")
    by_entity = repository.list_events_by_entity("entity-1")

    assert by_topic[0].event_id == "event-1"
    assert by_entity[0].entity_ids == ["entity-1"]
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "FROM memory_events e" in executed_sql
    assert "JOIN memory_event_entities" in executed_sql
    assert "WHERE e.topic = %s" in executed_sql


def test_postgres_memory_repository_appends_claim_history_and_links() -> None:
    connection = FakeConnection()
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    repository.append_claim_history(
        ClaimHistoryRecord(
            history_id="history-1",
            claim_id="claim-1",
            old_status="active",
            new_status="contradicted",
            old_confidence=0.8,
            new_confidence=0.4,
            reason="new evidence",
            evidence_id="ev-2",
        )
    )
    repository.link_event_entity("event-1", "entity-1")
    repository.link_event_claim("event-1", "claim-1")
    repository.link_event_evidence("event-1", "ev-1")

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO memory_claim_history" in executed_sql
    assert "INSERT INTO memory_event_entities" in executed_sql
    assert "INSERT INTO memory_event_claims" in executed_sql
    assert "INSERT INTO memory_event_evidence" in executed_sql


def test_postgres_memory_repository_finds_similar_events() -> None:
    connection = FakeConnection()
    connection.all_rows = [[_event_row("event-2")]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    result = repository.find_similar_events(
        EventMemory(
            event_id="event-1",
            event_type="general_news",
            title="AI update",
            summary="Summary",
            run_id="run-1",
            topic="AI",
        )
    )

    assert result[0].event_id == "event-2"
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "e.event_id <> %s" in executed_sql


def _event_row(event_id):
    return (
        event_id,
        "general_news",
        "AI update",
        "Summary",
        "run-1",
        datetime(2026, 5, 21, tzinfo=UTC),
        datetime(2026, 5, 21, tzinfo=UTC),
        "AI",
        0.4,
        0.7,
        "active",
        {"source": "test"},
        ["entity-1"],
        ["claim-1"],
        ["ev-1"],
    )
