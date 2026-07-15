from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from framework.events.ports import EventStorePort
from infrastructure.storage.events import (
    LocalJsonEventStore,
    SQLiteEventStore,
    event_store_from_env,
)


def test_event_store_factory_returns_file_backed_sqlite_without_dsn(
    tmp_path: Path,
) -> None:
    store = event_store_from_env(artifact_root=tmp_path, env={})

    assert isinstance(store, SQLiteEventStore)
    assert isinstance(store, EventStorePort)
    assert Path(store.database) == tmp_path / "_records" / "events.sqlite3"
    assert Path(store.database).is_file()
    assert store.durability_policy == {
        "journal_mode": "WAL",
        "synchronous": "FULL",
        "busy_timeout_ms": 5000,
        "host_scope": "single-host",
    }


def test_event_store_factory_uses_configured_artifact_root_from_environment(
    tmp_path: Path,
) -> None:
    store = event_store_from_env(
        env={
            "NEWS_ARTIFACT_ROOT": str(tmp_path),
            "NEWS_DATABASE_DSN": "   ",
        }
    )

    assert isinstance(store, SQLiteEventStore)
    assert Path(store.database) == tmp_path / "_records" / "events.sqlite3"


def test_event_store_factory_selects_canonical_postgres_for_nonempty_dsn(
    monkeypatch,
) -> None:
    module = ModuleType("infrastructure.storage.events.postgres")

    class FakePostgresDurableEventStore:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

    module.PostgresDurableEventStore = FakePostgresDurableEventStore
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.storage.events.postgres",
        module,
    )

    store = event_store_from_env(
        env={"NEWS_DATABASE_DSN": "  postgresql://example/test  "}
    )

    assert isinstance(store, FakePostgresDurableEventStore)
    assert store.dsn == "postgresql://example/test"


def test_jsonl_store_is_explicit_legacy_compatibility_not_factory_default(
    tmp_path: Path,
) -> None:
    durable = event_store_from_env(artifact_root=tmp_path, env={})
    legacy = LocalJsonEventStore(tmp_path / "legacy-jsonl")

    assert isinstance(durable, SQLiteEventStore)
    assert not isinstance(durable, LocalJsonEventStore)
    assert legacy.root == tmp_path / "legacy-jsonl"
