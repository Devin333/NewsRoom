from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from framework.events.ports import EventStorePort
from infrastructure.storage.events import (
    DurableEventStorage,
    LocalJsonEventStore,
    PostgresReplayCheckpointStore,
    SQLiteEventStore,
    SQLiteReplayCheckpointStore,
    durable_event_storage_from_env,
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


def test_durable_storage_package_exports_foundation_adapters() -> None:
    assert DurableEventStorage is not None
    assert durable_event_storage_from_env is not None
    assert SQLiteReplayCheckpointStore is not None
    assert PostgresReplayCheckpointStore is not None


def test_postgres_factory_optional_dependency_fails_with_typed_store_error() -> None:
    script = textwrap.dedent(
        """
        import builtins

        real_import = builtins.__import__

        def without_psycopg(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise ModuleNotFoundError(
                    "blocked optional psycopg dependency",
                    name="psycopg",
                )
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = without_psycopg

        from framework.events import EventStoreUnavailableError
        from infrastructure.storage.events import durable_event_storage_from_env

        try:
            durable_event_storage_from_env(
                env={"NEWS_DATABASE_DSN": "postgresql://example/test"}
            )
        except EventStoreUnavailableError:
            pass
        else:
            raise AssertionError("missing psycopg did not fail with EventStoreUnavailableError")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_postgres_factory_does_not_mask_unrelated_missing_dependency(
    monkeypatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def missing_driver_dependency(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "infrastructure.storage.events.postgres":
            raise ModuleNotFoundError(
                "missing unrelated driver dependency",
                name="driver_internal_dependency",
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_driver_dependency)

    with pytest.raises(ModuleNotFoundError) as error:
        durable_event_storage_from_env(
            env={"NEWS_DATABASE_DSN": "postgresql://example/test"}
        )

    assert error.value.name == "driver_internal_dependency"


def test_durable_storage_factory_composes_event_and_replay_stores_on_same_sqlite(
    tmp_path: Path,
) -> None:
    composition = durable_event_storage_from_env(artifact_root=tmp_path, env={})

    assert isinstance(composition, DurableEventStorage)
    assert isinstance(composition.event_store, SQLiteEventStore)
    assert isinstance(composition.replay_checkpoint_store, SQLiteReplayCheckpointStore)
    assert Path(composition.event_store.database) == Path(
        composition.replay_checkpoint_store.database
    )
    assert Path(composition.event_store.database).is_file()


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
    monkeypatch.setattr(
        "infrastructure.storage.events.factory.PostgresReplayCheckpointStore",
        FakePostgresDurableEventStore,
    )

    store = event_store_from_env(
        env={"NEWS_DATABASE_DSN": "  postgresql://example/test  "}
    )

    assert isinstance(store, FakePostgresDurableEventStore)
    assert store.dsn == "postgresql://example/test"


def test_durable_storage_factory_selects_postgres_without_memory_fallback(
    monkeypatch,
) -> None:
    events_module = ModuleType("infrastructure.storage.events.postgres")

    class FakePostgresDurableEventStore:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

    events_module.PostgresDurableEventStore = FakePostgresDurableEventStore
    monkeypatch.setitem(sys.modules, "infrastructure.storage.events.postgres", events_module)
    monkeypatch.setattr(
        "infrastructure.storage.events.factory.PostgresReplayCheckpointStore",
        FakePostgresDurableEventStore,
    )

    composition = durable_event_storage_from_env(
        env={"NEWS_DATABASE_DSN": "  postgresql://example/test  "}
    )

    assert isinstance(composition.event_store, FakePostgresDurableEventStore)
    assert isinstance(composition.replay_checkpoint_store, FakePostgresDurableEventStore)
    assert composition.event_store.dsn == "postgresql://example/test"
    assert composition.replay_checkpoint_store.dsn == "postgresql://example/test"


def test_jsonl_store_is_explicit_legacy_compatibility_not_factory_default(
    tmp_path: Path,
) -> None:
    durable = event_store_from_env(artifact_root=tmp_path, env={})
    legacy = LocalJsonEventStore(tmp_path / "legacy-jsonl")

    assert isinstance(durable, SQLiteEventStore)
    assert not isinstance(durable, LocalJsonEventStore)
    assert legacy.root == tmp_path / "legacy-jsonl"
