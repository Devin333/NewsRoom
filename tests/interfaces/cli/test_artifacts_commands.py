import json

import interfaces.cli.news as news_cli


def test_news_cli_artifacts_list_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "ArtifactInspectionService", _FakeArtifactService)

    exit_code = news_cli.main(["artifacts", "list", "--run-id", "run-1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["artifact_count"] == 1
    assert payload["artifacts"][0]["artifact_key"] == "output"


def test_news_cli_artifacts_show_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "ArtifactInspectionService", _FakeArtifactService)

    exit_code = news_cli.main(
        ["artifacts", "show", "--run-id", "run-1", "--artifact-key", "output", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["artifact_key"] == "output"
    assert payload["content"] == {"status": "ok"}


class _FakeArtifactService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_count": 1,
                "artifacts": [
                    {
                        "artifact_key": "output",
                        "relative_path": "output.json",
                        "content_type": "application/json",
                        "size_bytes": 14,
                    }
                ],
            }
        )

    def get_artifact(self, run_id, artifact_key):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_key": artifact_key,
                "relative_path": "output.json",
                "content_type": "application/json",
                "size_bytes": 14,
                "content": {"status": "ok"},
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
