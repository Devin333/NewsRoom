from __future__ import annotations

from business.research.reader_repair import ReaderRepairService
from interfaces.services.reader_repair_memory import (
    PostgresReaderRepairMemoryCommitPort,
)
from interfaces.services import reader_repair_factory


def test_reader_repair_memory_factory_returns_none_without_database_dsn() -> None:
    assert reader_repair_factory.build_reader_repair_memory_from_env(env={}) is None
    assert (
        reader_repair_factory.build_reader_repair_memory_commit_port_from_env(
            env={}
        )
        is None
    )


def test_reader_repair_service_factory_uses_postgres_memory_when_dsn_is_configured(
    monkeypatch,
) -> None:
    created = {}

    class FakeRepository:
        def __init__(self, dsn):
            created["dsn"] = dsn

    monkeypatch.setattr(
        reader_repair_factory,
        "PostgresReaderRepairMemoryRepository",
        FakeRepository,
    )

    service = reader_repair_factory.build_reader_repair_service_from_env(
        env={"NEWS_DATABASE_DSN": "postgresql://example"}
    )

    assert isinstance(service, ReaderRepairService)
    assert service.memory_service.memory.__class__.__name__ == "PostgresReaderRepairMemoryPort"
    assert created["dsn"] == "postgresql://example"


def test_reader_repair_commit_port_factory_builds_inactive_postgres_adapter(
    monkeypatch,
) -> None:
    created = {}

    class FakeRepository:
        def __init__(self, dsn):
            created["dsn"] = dsn

    monkeypatch.setattr(
        reader_repair_factory,
        "PostgresReaderRepairMemoryRepository",
        FakeRepository,
    )

    port = reader_repair_factory.build_reader_repair_memory_commit_port_from_env(
        env={"NEWS_DATABASE_DSN": "postgresql://example"}
    )

    assert isinstance(port, PostgresReaderRepairMemoryCommitPort)
    assert created["dsn"] == "postgresql://example"
