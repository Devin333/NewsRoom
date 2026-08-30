from datetime import UTC, datetime

from backend.memory.intelligence_models import ClaimHistoryRecord, EventMemory, PreferenceMemory
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
    repository.link_event_entity("event-1", "entity-1", role="primary")
    repository.link_event_claim("event-1", "claim-1", role="background")
    repository.link_event_evidence("event-1", "ev-1", support_type="contradicting")

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO memory_claim_history" in executed_sql
    assert "INSERT INTO memory_event_entities (event_id, entity_id, role)" in executed_sql
    assert "INSERT INTO memory_event_claims (event_id, claim_id, role)" in executed_sql
    assert "INSERT INTO memory_event_evidence (event_id, evidence_id, support_type)" in executed_sql
    assert ("event-1", "entity-1", "primary") in [params for _, params in connection.calls]
    assert ("event-1", "claim-1", "background") in [params for _, params in connection.calls]
    assert ("event-1", "ev-1", "contradicting") in [params for _, params in connection.calls]


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


def test_postgres_memory_repository_save_events_refreshes_relation_refs() -> None:
    connection = FakeConnection()
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    repository.save_events(
        [
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="AI update",
                summary="Summary",
                run_id="run-1",
                topic="AI",
                entity_ids=["entity-1"],
                claim_ids=["claim-1"],
                evidence_ids=["ev-1"],
            )
        ]
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO memory_events" in executed_sql
    assert "DELETE FROM memory_event_entities WHERE event_id = %s" in executed_sql
    assert "INSERT INTO memory_event_entities (event_id, entity_id, role)" in executed_sql
    assert "INSERT INTO memory_event_claims (event_id, claim_id, role)" in executed_sql
    assert "INSERT INTO memory_event_evidence (event_id, evidence_id, support_type)" in executed_sql
    assert ("event-1", "entity-1", "mentioned") in [params for _, params in connection.calls]
    assert ("event-1", "claim-1", "supporting") in [params for _, params in connection.calls]
    assert ("event-1", "ev-1", "supporting") in [params for _, params in connection.calls]


def test_postgres_memory_repository_lists_claims_by_topic() -> None:
    connection = FakeConnection()
    connection.all_rows = [[(_claim_payload("claim-1"),)]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    claims = repository.list_claims_by_topic("AI")

    assert claims[0].claim_id == "claim-1"
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "FROM claims" in executed_sql
    assert "payload::text ILIKE %s" in executed_sql


def test_postgres_memory_repository_lists_evidence_for_claim() -> None:
    connection = FakeConnection()
    connection.all_rows = [[(_evidence_payload("ev-1"),)]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    evidence = repository.list_evidence_for_claim("claim-1")

    assert evidence[0].evidence_id == "ev-1"
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "FROM claim_supports cs" in executed_sql
    assert "JOIN evidence_items e ON e.evidence_id = cs.evidence_id" in executed_sql


def test_postgres_memory_repository_lists_decisions_for_target() -> None:
    connection = FakeConnection()
    connection.all_rows = [[_decision_row("decision-1")]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    decisions = repository.list_decisions_for_target("report", "report-1")

    assert decisions[0].decision_id == "decision-1"
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "FROM memory_decisions" in executed_sql
    assert "WHERE target_type = %s AND target_id = %s" in executed_sql


def test_postgres_memory_repository_lists_preferences() -> None:
    connection = FakeConnection()
    connection.all_rows = [[_preference_row("pref-1")]]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    preferences = repository.list_preferences(
        owner_type="report",
        owner_id="report-1",
        preference_type="tone",
    )

    assert preferences[0] == PreferenceMemory(
        preference_id="pref-1",
        owner_type="report",
        owner_id="report-1",
        preference_type="tone",
        content="Concise",
        weight=0.8,
        source="editor",
        created_at=datetime(2026, 5, 21, tzinfo=UTC),
        metadata={"source": "test"},
    )
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "FROM memory_preferences" in executed_sql
    assert "preference_type = %s" in executed_sql


def test_postgres_memory_repository_update_claim_status_appends_history() -> None:
    connection = FakeConnection()
    connection.one_rows = [(_claim_payload("claim-1"),)]
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    repository.update_claim_status(
        "claim-1",
        status="contradicted",
        confidence=0.3,
        reason="new evidence",
        evidence_id="ev-2",
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "SELECT payload FROM claims WHERE claim_id = %s" in executed_sql
    assert "INSERT INTO memory_claim_history" in executed_sql
    assert any(
        params and len(params) > 3 and params[1] == "claim-1" and params[2] == "active"
        for _, params in connection.calls
    )


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


def _claim_payload(claim_id):
    return {
        "claim_id": claim_id,
        "run_id": "run-1",
        "text": "OpenAI shipped memory.",
        "status": "active",
        "confidence": 0.8,
        "evidence_ids": ["ev-1"],
        "metadata": {"topic": "AI"},
    }


def _evidence_payload(evidence_id):
    return {
        "evidence_id": evidence_id,
        "run_id": "run-1",
        "title": "OpenAI shipped memory",
        "summary": "Summary",
        "source_urls": ["https://example.com"],
        "source_item_ids": ["item-1"],
        "confidence": 0.8,
        "metadata": {"topic": "AI"},
    }


def _decision_row(decision_id):
    return (
        decision_id,
        "quality_gate",
        "report",
        "report-1",
        "pass",
        "supported",
        "run-1",
        "research.paper-analysis",
        "1",
        "research.paper-analysis@1",
        "sha256:" + "a" * 64,
        "agent-1",
        {"quality": 0.9},
        {"score": 0.9},
        datetime(2026, 5, 21, tzinfo=UTC),
        {"source": "test"},
    )


def _preference_row(preference_id):
    return (
        preference_id,
        "report",
        "report-1",
        "tone",
        "Concise",
        0.8,
        "editor",
        datetime(2026, 5, 21, tzinfo=UTC),
        None,
        None,
        {"source": "test"},
    )
