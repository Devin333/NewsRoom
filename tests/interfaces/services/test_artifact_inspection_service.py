import json

import pytest

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
)
from framework.harness.artifacts import (
    GraphTerminalManifestHistoryError,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from tests.fixtures.graph_runs import (
    rewrite_graph_terminal_manifest,
    write_graph_terminal_run,
)


def test_artifact_service_lists_graph_terminal_manifest_artifacts(tmp_path) -> None:
    fixture = write_graph_terminal_run(
        tmp_path,
        files={
            "output": ("output.json", {"status": "ok"}),
            "report_markdown": ("report.md", "# Report"),
        },
    )

    result = ArtifactInspectionService(tmp_path).list_artifacts("run-1")

    payload = result.to_dict()
    artifacts_by_key = {
        artifact["artifact_key"]: artifact for artifact in payload["artifacts"]
    }
    assert payload["artifact_count"] == len(fixture.manifest.artifacts)
    assert artifacts_by_key["output"]["content_type"] == "application/json"
    assert artifacts_by_key["report_markdown"]["content_type"] == "text/markdown"
    assert artifacts_by_key["output"]["size_bytes"] > 0


def test_artifact_service_reads_verified_json_artifact(tmp_path) -> None:
    write_graph_terminal_run(
        tmp_path,
        files={"output": ("output.json", {"status": "ok"})},
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert result.to_dict()["content"] == {"status": "ok"}
    assert result.to_dict()["size_bytes"] is not None


def test_artifact_service_redacts_sensitive_json_fields(tmp_path) -> None:
    write_graph_terminal_run(
        tmp_path,
        files={
            "output": (
                "output.json",
                {
                    "token": "hidden",
                    "nested": {"api_key": "secret"},
                    "safe": "ok",
                },
            )
        },
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert result.to_dict()["content"] == {
        "token": "[redacted]",
        "nested": {"api_key": "[redacted]"},
        "safe": "ok",
    }


def test_artifact_service_redacts_sensitive_jsonl_fields(tmp_path) -> None:
    write_graph_terminal_run(
        tmp_path,
        files={
            "events": (
                "events.jsonl",
                '{"payload": {"token": "hidden", "safe": "ok"}}\n',
            )
        },
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "events")

    assert '"token": "[redacted]"' in result.to_dict()["content"]
    assert "hidden" not in result.to_dict()["content"]
    assert '"safe": "ok"' in result.to_dict()["content"]


def test_artifact_service_rejects_tampered_content(tmp_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    fixture.artifact_path("output").write_text(
        json.dumps({"status": "tampered"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactChecksumMismatchError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


@pytest.mark.parametrize("checksum", [None, "invalid", "sha256:" + "A" * 64])
def test_artifact_service_rejects_missing_or_invalid_checksum(tmp_path, checksum) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    if checksum is None:
        manifest["artifacts"][0].pop("content_checksum")
    else:
        manifest["artifacts"][0]["content_checksum"] = checksum
    rewrite_graph_terminal_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_manifest_listed_missing_file(tmp_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    fixture.artifact_path("output").unlink()

    with pytest.raises(ArtifactNotFoundError, match="output.json"):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_unknown_artifact_key(tmp_path) -> None:
    write_graph_terminal_run(tmp_path, files={})

    with pytest.raises(ArtifactNotFoundError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "missing")


def test_artifact_service_rejects_invalid_graph_manifest_before_artifact_read(
    tmp_path,
) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    manifest.pop("graph_id")
    rewrite_graph_terminal_manifest(fixture, manifest)
    fixture.artifact_path("output").unlink()

    with pytest.raises(ArtifactStoreMetadataError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_returns_typed_history_diagnostic_without_reading_content(
    tmp_path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "newsroom.workflow_run_manifest.v1",
                "run_id": "run-1",
                "artifacts": {"output": "output.json"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "output.json").write_text('{"token":"must-not-be-read"}')

    with pytest.raises(GraphTerminalManifestHistoryError) as raised:
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert raised.value.diagnostic.run_id == "run-1"
    assert raised.value.diagnostic.disposition == "quarantine"
    assert raised.value.diagnostic.publishable is False


@pytest.mark.parametrize(
    "run_id",
    ["../secret", "C:secret", "run:stream", "CON", "run. "],
)
def test_artifact_service_rejects_unsafe_run_id_before_reading(tmp_path, run_id) -> None:
    with pytest.raises(ArtifactPathError):
        ArtifactInspectionService(tmp_path).get_artifact(run_id, "output")


@pytest.mark.parametrize(
    "relative_path",
    ["../secret.json", "C:secret.json", "\\\\server\\share\\secret.json", "a:stream"],
)
def test_artifact_service_rejects_unsafe_manifest_path(tmp_path, relative_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    manifest = fixture.manifest.to_dict()
    manifest["artifacts"][0]["relative_path"] = relative_path
    manifest["manifest_hash"] = None
    rewrite_graph_terminal_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_symlink_escape(tmp_path) -> None:
    fixture = write_graph_terminal_run(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked": true}', encoding="utf-8")
    link = fixture.artifact_path("output")
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    with pytest.raises((ArtifactPathError, ArtifactStoreMetadataError)):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")
