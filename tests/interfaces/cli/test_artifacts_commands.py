import json

import pytest

import interfaces.cli.news as news_cli
from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from interfaces.cli.commands import artifacts as artifact_commands
from tests.fixtures.workflow_runs import rewrite_manifest, write_canonical_terminal_run


def test_news_cli_artifacts_list_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(artifact_commands, "ArtifactInspectionService", _FakeArtifactService)

    exit_code = news_cli.main(["artifacts", "list", "--run-id", "run-1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["artifact_count"] == 1
    assert payload["artifacts"][0]["artifact_key"] == "output"


def test_news_cli_artifacts_show_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(artifact_commands, "ArtifactInspectionService", _FakeArtifactService)

    exit_code = news_cli.main(
        ["artifacts", "show", "--run-id", "run-1", "--artifact-key", "output", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["artifact_key"] == "output"
    assert payload["content"] == {"status": "ok"}


def test_news_cli_artifacts_list_path_error_uses_stderr_and_exit_one(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        artifact_commands,
        "ArtifactInspectionService",
        _ArtifactPathErrorService,
    )

    exit_code = news_cli.main(["artifacts", "list", "--run-id", "run:stream", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid artifact path" in captured.err


def test_news_cli_artifacts_show_path_error_does_not_print_content(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        artifact_commands,
        "ArtifactInspectionService",
        _ArtifactPathErrorService,
    )

    exit_code = news_cli.main(
        ["artifacts", "show", "--run-id", "run-1", "--artifact-key", "output"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid artifact path" in captured.err
    assert "artifact-secret" not in captured.err


@pytest.mark.parametrize(
    "error_type",
    [
        ArtifactChecksumMismatchError,
        ArtifactStoreMetadataError,
        ArtifactStoreRequiredError,
    ],
)
def test_news_cli_artifacts_show_integrity_error_uses_stderr_and_exit_one(
    monkeypatch,
    capsys,
    error_type,
) -> None:
    error = error_type("artifact integrity verification failed")
    monkeypatch.setattr(
        artifact_commands,
        "ArtifactInspectionService",
        lambda *args, **kwargs: _ArtifactIntegrityErrorService(error),
    )

    exit_code = news_cli.main(
        ["artifacts", "show", "--run-id", "run-1", "--artifact-key", "output", "--json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "artifact integrity verification failed\n"


def test_news_cli_artifacts_show_real_missing_checksum_does_not_print_content(
    tmp_path,
    capsys,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = dict(fixture.manifest)
    manifest["artifact_metadata"] = {
        key: dict(value) for key, value in fixture.manifest["artifact_metadata"].items()
    }
    manifest["artifact_metadata"]["output"].pop("checksum")
    rewrite_manifest(fixture, manifest)

    exit_code = news_cli.main(
        [
            "artifacts",
            "show",
            "--run-id",
            "run-1",
            "--artifact-key",
            "output",
            "--artifact-root",
            str(tmp_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid canonical run manifest" in captured.err
    assert "fixture-secret-token" not in captured.err


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


class _ArtifactPathErrorService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        raise ArtifactPathError("invalid artifact path")

    def get_artifact(self, run_id, artifact_key):
        raise ArtifactPathError("invalid artifact path")


class _ArtifactIntegrityErrorService:
    def __init__(self, error) -> None:
        self.error = error

    def get_artifact(self, run_id, artifact_key):
        raise self.error


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
