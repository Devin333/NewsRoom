from infrastructure.storage.artifacts import LocalJsonArtifactIndexStore, artifact_index_store_from_env


def test_artifact_index_factory_returns_local_json_without_dsn(tmp_path) -> None:
    store = artifact_index_store_from_env(artifact_root=tmp_path, env={})

    assert isinstance(store, LocalJsonArtifactIndexStore)
    assert store.root == tmp_path / "_records" / "artifact_index"


def test_artifact_index_factory_returns_postgres_with_dsn() -> None:
    store = artifact_index_store_from_env(env={"NEWS_DATABASE_DSN": "postgresql://example"})

    assert store.__class__.__name__ == "PostgresArtifactIndexStore"
