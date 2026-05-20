from infrastructure.storage.metrics import LocalStorageMetricsCollector, storage_metrics_collector_from_env


def test_storage_metrics_factory_returns_local_collector_without_dsn(tmp_path) -> None:
    collector = storage_metrics_collector_from_env(artifact_root=tmp_path, env={})

    assert isinstance(collector, LocalStorageMetricsCollector)
    assert collector.artifact_root == tmp_path


def test_storage_metrics_factory_returns_postgres_collector_with_dsn() -> None:
    collector = storage_metrics_collector_from_env(env={"NEWS_DATABASE_DSN": "postgresql://example"})

    assert collector.__class__.__name__ == "PostgresStorageMetricsCollector"
