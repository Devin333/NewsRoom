import json
from dataclasses import replace

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from tests.fixtures.workflow_runs import (
    rewrite_manifest,
    write_canonical_terminal_run,
)


def test_artifact_service_lists_manifest_artifacts(tmp_path) -> None:
    fixture = _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json", "report_markdown": "report.md"},
        files={"output.json": {"status": "ok"}, "report.md": "# Report"},
    )

    result = ArtifactInspectionService(tmp_path).list_artifacts("run-1")

    payload = result.to_dict()
    artifacts_by_key = {
        artifact["artifact_key"]: artifact for artifact in payload["artifacts"]
    }
    assert payload["artifact_count"] == len(fixture.manifest["artifacts"])
    assert artifacts_by_key["output"]["content_type"] == "application/json"
    assert artifacts_by_key["report_markdown"]["content_type"] == "text/markdown"


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


def test_artifact_service_rejects_invalid_canonical_manifest_before_artifact_read(
    tmp_path,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = dict(fixture.manifest)
    manifest.pop("workflow_id")
    rewrite_manifest(fixture, manifest)
    fixture.artifact_path("output").unlink()

    with pytest.raises(ArtifactStoreMetadataError, match="invalid canonical run manifest"):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def test_artifact_service_resolves_missing_artifact_dir_through_shared_boundary(
    tmp_path,
    monkeypatch,
) -> None:
    write_canonical_terminal_run(
        tmp_path,
        terminal_content={"status": "ok", "result": "fallback"},
    )
    service = ArtifactInspectionService(tmp_path)
    detail = service.run_inspection.get_run("run-1")
    monkeypatch.setattr(
        service.run_inspection,
        "get_run",
        lambda run_id: replace(detail, artifact_dir=None),
    )

    result = service.get_artifact("run-1", "output")

    assert result.content == {"status": "ok", "result": "fallback"}


def test_artifact_service_fallback_rejects_unsafe_run_id_before_filesystem_read(
    tmp_path,
    monkeypatch,
) -> None:
    write_canonical_terminal_run(tmp_path)
    service = ArtifactInspectionService(tmp_path)
    detail = service.run_inspection.get_run("run-1")
    monkeypatch.setattr(
        service.run_inspection,
        "get_run",
        lambda run_id: replace(detail, artifact_dir=None),
    )

    with pytest.raises(ArtifactPathError):
        service.get_artifact("../run-1", "output")


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
    fixture = write_canonical_terminal_run(tmp_path)
    run_dir = fixture.run_dir
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked": true}', encoding="utf-8")
    link = run_dir / "output.json"
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    with pytest.raises(ValueError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")


def _write_run(root, run_id, *, artifacts, files):
    encoded_files = {
        relative_path: (
            content.encode("utf-8")
            if isinstance(content, str)
            else json.dumps(content).encode("utf-8")
        )
        for relative_path, content in files.items()
    }
    extra_artifacts = {
        artifact_key: (relative_path, encoded_files[relative_path])
        for artifact_key, relative_path in artifacts.items()
        if relative_path in encoded_files
    }
    fixture = write_canonical_terminal_run(
        root,
        run_id,
        extra_artifacts=extra_artifacts,
    )
    missing_artifacts = {
        artifact_key: relative_path
        for artifact_key, relative_path in artifacts.items()
        if relative_path not in encoded_files
    }
    if missing_artifacts:
        manifest = dict(fixture.manifest)
        manifest["artifacts"] = {
            **fixture.manifest["artifacts"],
            **missing_artifacts,
        }
        artifact_metadata = dict(fixture.manifest["artifact_metadata"])
        for artifact_key in missing_artifacts:
            artifact_metadata.pop(artifact_key, None)
        manifest["artifact_metadata"] = artifact_metadata
        rewrite_manifest(fixture, manifest)
    return fixture
