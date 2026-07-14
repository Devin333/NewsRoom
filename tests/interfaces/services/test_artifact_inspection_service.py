import json
from hashlib import sha256

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from interfaces.services.artifact_service import ArtifactInspectionService


def test_artifact_service_lists_manifest_artifacts(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json", "report_markdown": "report.md"},
        files={"output.json": {"status": "ok"}, "report.md": "# Report"},
    )

    result = ArtifactInspectionService(tmp_path).list_artifacts("run-1")

    payload = result.to_dict()
    assert payload["artifact_count"] == 2
    assert payload["artifacts"][0]["artifact_key"] == "output"
    assert payload["artifacts"][0]["content_type"] == "application/json"
    assert payload["artifacts"][1]["artifact_key"] == "report_markdown"
    assert payload["artifacts"][1]["content_type"] == "text/markdown"


def test_artifact_service_reads_json_artifact(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"status": "ok"}},
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert result.to_dict()["content"] == {"status": "ok"}
    assert result.to_dict()["size_bytes"] is not None


def test_artifact_service_redacts_sensitive_json_fields(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"token": "hidden", "nested": {"api_key": "secret"}, "safe": "ok"}},
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert result.to_dict()["content"] == {
        "token": "[redacted]",
        "nested": {"api_key": "[redacted]"},
        "safe": "ok",
    }


def test_artifact_service_redacts_sensitive_jsonl_fields(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"events": "events.jsonl"},
        files={"events.jsonl": '{"payload": {"token": "hidden", "safe": "ok"}}\n'},
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "events")

    assert '"token": "[redacted]"' in result.to_dict()["content"]
    assert "hidden" not in result.to_dict()["content"]
    assert '"safe": "ok"' in result.to_dict()["content"]


def test_artifact_service_rejects_tampered_content(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"status": "ok"}},
    )
    (tmp_path / "run-1" / "output.json").write_text(
        json.dumps({"status": "tampered"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactChecksumMismatchError, match="output"):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


@pytest.mark.parametrize("checksum", [None, "invalid", "A" * 64])
def test_artifact_service_rejects_missing_or_invalid_checksum(tmp_path, checksum) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"status": "ok"}},
    )
    manifest_path = tmp_path / "run-1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if checksum is None:
        manifest["artifact_metadata"]["output"].pop("checksum")
    else:
        manifest["artifact_metadata"]["output"]["checksum"] = checksum
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArtifactStoreMetadataError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_manifest_listed_missing_file(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"status": "ok"}},
    )
    (tmp_path / "run-1" / "output.json").unlink()

    with pytest.raises(ArtifactNotFoundError, match="output.json"):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_unknown_artifact_key(tmp_path) -> None:
    _write_run(tmp_path, "run-1", artifacts={}, files={})

    with pytest.raises(FileNotFoundError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "missing")


@pytest.mark.parametrize(
    "run_id",
    ["../secret", "C:secret", "run:stream", "CON", "run. "],
)
def test_artifact_service_rejects_unsafe_run_id_before_reading(tmp_path, run_id) -> None:
    with pytest.raises(ValueError):
        ArtifactInspectionService(tmp_path).get_artifact(run_id, "output")


@pytest.mark.parametrize(
    "relative_path",
    ["../secret.json", "C:secret.json", "\\\\server\\share\\secret.json", "a:stream"],
)
def test_artifact_service_rejects_unsafe_manifest_path(tmp_path, relative_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": relative_path},
        files={},
    )

    with pytest.raises(ValueError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_rejects_symlink_escape(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked": true}', encoding="utf-8")
    link = run_dir / "output.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": {"output": "output.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def _write_run(root, run_id, *, artifacts, files) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    encoded_files = {
        relative_path: (
            content.encode("utf-8")
            if isinstance(content, str)
            else json.dumps(content).encode("utf-8")
        )
        for relative_path, content in files.items()
    }
    artifact_metadata = {
        artifact_key: {
            "checksum": sha256(encoded_files[relative_path]).hexdigest(),
            "content_type": (
                "application/x-ndjson"
                if relative_path.endswith(".jsonl")
                else "application/json"
                if relative_path.endswith(".json")
                else "text/markdown"
                if relative_path.endswith(".md")
                else "text/plain"
            ),
            "size_bytes": len(encoded_files[relative_path]),
        }
        for artifact_key, relative_path in artifacts.items()
        if relative_path in encoded_files
    }
    manifest = {
        "run_id": run_id,
        "status": "succeeded",
        "artifacts": artifacts,
        "artifact_metadata": artifact_metadata,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, content in encoded_files.items():
        path = run_dir / relative_path
        path.write_bytes(content)
