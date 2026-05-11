import json

import interfaces.cli.news as news_cli


def test_news_cli_storage_metrics_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(["storage", "metrics", "--artifact-root", "runs", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["runs_count"] == 1
    assert payload["artifacts_count"] == 2
    assert payload["metadata"]["artifact_root"] == "runs"


def test_news_cli_storage_metrics_text(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(["storage", "metrics", "--artifact-root", "runs"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "runs_count=1" in captured.out
    assert "lineage_refs_count=4" in captured.out


def test_news_cli_storage_migrate_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(
        ["storage", "migrate", "--artifact-root", "runs", "--require-postgres", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["migrated"] is True
    assert payload["backend"] == "_FakePostgresRepository"
    assert payload["postgres_required"] is True
    assert "dsn" not in captured.out.lower()


def test_news_cli_storage_migrate_require_postgres_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _RejectingStorageService)

    exit_code = news_cli.main(["storage", "migrate", "--artifact-root", "runs", "--require-postgres"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NEWS_DATABASE_DSN" in captured.out


class _FakeStorageService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def metrics(self):
        return _FakeMetrics(
            {
                "runs_count": 1,
                "reports_count": 1,
                "artifacts_count": 2,
                "artifact_bytes_total": 42,
                "events_count": 3,
                "lineage_refs_count": 4,
                "generated_at": "2026-05-11T01:00:00Z",
                "metadata": {"artifact_root": self.artifact_root, "source": "test"},
            }
        )

    def migrate_persistence(self, *, require_postgres=False):
        return _FakeMetrics(
            {
                "artifact_root": self.artifact_root,
                "backend": "_FakePostgresRepository",
                "postgres_required": require_postgres,
                "migrated": True,
            }
        )


class _RejectingStorageService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def migrate_persistence(self, *, require_postgres=False):
        raise ValueError("PostgreSQL migration requires NEWS_DATABASE_DSN")


class _FakeMetrics:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
