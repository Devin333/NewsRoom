from datetime import UTC, datetime

from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)
from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository
from infrastructure.storage.postgres.repository import PostgresRepository


class FakeCursor:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        self.commits += 1


def test_postgres_intelligence_repository_reuses_evidence_and_claim_writes() -> None:
    connection = FakeConnection()
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    repository.save_evidence(
        [
            EvidenceMemory(
                evidence_id="ev-1",
                run_id="run-1",
                title="Title",
                summary="Summary",
                source_urls=["https://example.com"],
                source_item_ids=["raw-1"],
                confidence=0.8,
            )
        ]
    )
    repository.save_claims(
        [
            ClaimMemory(
                claim_id="claim-1",
                run_id="run-1",
                text="Summary",
                confidence=0.8,
                evidence_ids=["ev-1"],
            )
        ]
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO evidence_items" in executed_sql
    assert "INSERT INTO claims" in executed_sql
    assert "INSERT INTO claim_supports" in executed_sql


def test_postgres_intelligence_repository_upserts_objects_and_event_refs() -> None:
    connection = FakeConnection()
    repository = PostgresIntelligenceMemoryRepository(
        PostgresRepository("postgresql://example", connection_factory=lambda: connection)
    )

    repository.save_entities(
        [EntityMemory(entity_id="ent-1", entity_type="topic", canonical_name="AI")]
    )
    repository.save_events(
        [
            EventMemory(
                event_id="event-1",
                event_type="general_news",
                title="Update",
                summary="Summary",
                run_id="run-1",
                entity_ids=["ent-1"],
                claim_ids=["claim-1"],
                evidence_ids=["ev-1"],
            )
        ]
    )
    repository.save_decisions(
        [
            DecisionMemory(
                decision_id="decision-1",
                decision_type="quality_gate",
                target_type="report",
                target_id="run-1:final",
                decision="pass",
                run_id="run-1",
                created_at=datetime(2026, 5, 21, tzinfo=UTC),
            )
        ]
    )
    repository.save_preferences(
        [
            PreferenceMemory(
                preference_id="pref-1",
                owner_type="project",
                owner_id="newsroom",
                preference_type="topic",
                content="AI",
            )
        ]
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO memory_entities" in executed_sql
    assert "INSERT INTO memory_events" in executed_sql
    assert "DELETE FROM memory_event_entities" in executed_sql
    assert "INSERT INTO memory_event_entities" in executed_sql
    assert "INSERT INTO memory_event_claims" in executed_sql
    assert "INSERT INTO memory_event_evidence" in executed_sql
    assert "INSERT INTO memory_decisions" in executed_sql
    assert "INSERT INTO memory_preferences" in executed_sql
