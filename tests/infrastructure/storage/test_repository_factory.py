from infrastructure.storage.records import ReportDetailRecord, ReportSummaryRecord
from infrastructure.storage.repository import LocalJsonPersistenceAdapter, repository_from_env


def test_repository_factory_returns_local_json_without_dsn(tmp_path) -> None:
    repository = repository_from_env(artifact_root=tmp_path, env={})

    assert isinstance(repository, LocalJsonPersistenceAdapter)
    assert hasattr(repository, "latest_report")
    assert hasattr(repository, "list_claims")


def test_repository_factory_returns_postgres_with_dsn() -> None:
    repository = repository_from_env(env={"NEWS_DATABASE_DSN": "postgresql://example"})

    assert repository.__class__.__name__ == "PostgresRepository"
    assert hasattr(repository, "latest_report")
    assert hasattr(repository, "list_quality_results")
