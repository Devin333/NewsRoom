import json

import interfaces.cli.news as news_cli


def test_news_cli_storage_retention_plan_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(
        [
            "storage",
            "retention",
            "plan",
            "--artifact-root",
            "runs",
            "--now",
            "2026-05-11T00:00:00Z",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["artifact_root"] == "runs"
    assert payload["delete_count"] == 1


def test_news_cli_storage_retention_plan_text(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(["storage", "retention", "plan", "--artifact-root", "runs"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "artifact_count=2" in captured.out
    assert "delete_count=1" in captured.out


def test_news_cli_storage_retention_apply_requires_yes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(["storage", "retention", "apply", "--artifact-root", "runs"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "requires --yes" in captured.out


def test_news_cli_storage_retention_apply_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "StorageApplicationService", _FakeStorageService)

    exit_code = news_cli.main(
        ["storage", "retention", "apply", "--artifact-root", "runs", "--yes", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["deleted_count"] == 1


class _FakeStorageService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def plan_retention(self, **kwargs):
        return _FakeResult(_payload(self.artifact_root))

    def apply_retention(self, **kwargs):
        payload = _payload(self.artifact_root)
        payload["deleted_count"] = 1
        payload["deleted_artifacts"] = [payload["plan"]["decisions"][0]["artifact_ref"]]
        return _FakeResult(payload)


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


def _payload(artifact_root):
    return {
        "artifact_root": artifact_root,
        "run_id": None,
        "policy": {
            "raw_source_retention_days": 30,
            "llm_artifact_retention_days": 90,
            "run_artifact_retention_days": 180,
            "report_retention_days": None,
            "evidence_retention_days": None,
            "vector_retention_days": None,
        },
        "artifact_count": 2,
        "delete_count": 1,
        "keep_count": 1,
        "plan": {
            "generated_at": "2026-05-11T00:00:00Z",
            "delete_count": 1,
            "keep_count": 1,
            "decisions": [
                {
                    "action": "delete",
                    "reason": "retention_expired",
                    "expires_at": "2026-05-01T00:00:00Z",
                    "artifact_ref": {"artifact_id": "raw-old", "run_id": "run-1"},
                }
            ],
        },
    }
