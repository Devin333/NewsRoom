from storage.lineage import LocalJsonLineageStore, lineage_store_from_env


def test_lineage_store_factory_returns_local_json_without_dsn(tmp_path) -> None:
    store = lineage_store_from_env(artifact_root=tmp_path, env={})

    assert isinstance(store, LocalJsonLineageStore)
    assert store.root == tmp_path / "_records" / "lineage"


def test_lineage_store_factory_returns_postgres_with_dsn() -> None:
    store = lineage_store_from_env(env={"NEWS_DATABASE_DSN": "postgresql://example"})

    assert store.__class__.__name__ == "PostgresLineageStore"
