from storage.events import LocalJsonEventStore, event_store_from_env


def test_event_store_factory_returns_local_json_without_dsn(tmp_path) -> None:
    store = event_store_from_env(artifact_root=tmp_path, env={})

    assert isinstance(store, LocalJsonEventStore)
    assert store.root == tmp_path / "_records" / "events"


def test_event_store_factory_returns_postgres_with_dsn() -> None:
    store = event_store_from_env(env={"NEWS_DATABASE_DSN": "postgresql://example"})

    assert store.__class__.__name__ == "PostgresEventStore"
